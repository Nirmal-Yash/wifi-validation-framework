#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, RunEvent, State};

struct BackendState {
    base_url: String,
    child: Mutex<Option<Child>>,
}

fn io_error(message: impl Into<String>) -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::Other, message.into())
}

fn ensure_private_directory(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    fs::create_dir_all(path)?;
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(io_error("application data path must be a real directory").into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn choose_loopback_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

fn backend_executable(resource_dir: &Path) -> PathBuf {
    resource_dir.join("backend").join("netregress-backend")
}

fn wait_for_backend(child: &mut Child, port: u16) -> Result<(), Box<dyn std::error::Error>> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let started = Instant::now();
    let timeout = Duration::from_secs(35);
    while started.elapsed() < timeout {
        if let Some(status) = child.try_wait()? {
            return Err(io_error(format!(
                "NetRegress backend exited during startup with status {status}; inspect the backend log under the application data directory"
            )).into());
        }
        if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) {
            stream.set_read_timeout(Some(Duration::from_secs(2)))?;
            stream.write_all(
                b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
            )?;
            let mut reader = BufReader::new(stream);
            let mut status_line = String::new();
            if reader.read_line(&mut status_line).is_ok()
                && (status_line.starts_with("HTTP/1.1 200")
                    || status_line.starts_with("HTTP/1.0 200"))
            {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    let _ = child.kill();
    let _ = child.wait();
    Err(io_error(
        "NetRegress backend did not become healthy within 35 seconds; inspect the backend log under the application data directory",
    ).into())
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

#[tauri::command]
fn api_base_url(state: State<'_, BackendState>) -> String {
    state.base_url.clone()
}

fn main() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![api_base_url])
        .setup(|app| {
            let data_dir = app.path().app_data_dir()?;
            let config_dir = app.path().app_config_dir()?;
            let logs_dir = data_dir.join("logs");
            let results_dir = data_dir.join("results");
            let runtime_dir = data_dir.join("runtime");
            let process_dir = results_dir.join("processes");
            for directory in [
                data_dir.as_path(),
                config_dir.as_path(),
                logs_dir.as_path(),
                results_dir.as_path(),
                runtime_dir.as_path(),
                process_dir.as_path(),
            ] {
                ensure_private_directory(directory)?;
            }

            let resource_dir = app.path().resource_dir()?;
            let executable = backend_executable(&resource_dir);
            if !executable.is_file() {
                return Err(io_error(format!(
                    "packaged backend is missing: {}",
                    executable.display()
                )).into());
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let mut permissions = fs::metadata(&executable)?.permissions();
                if permissions.mode() & 0o111 == 0 {
                    permissions.set_mode(0o700);
                    fs::set_permissions(&executable, permissions)?;
                }
            }

            let port = choose_loopback_port()?;
            let log_path = logs_dir.join("backend.log");
            let mut log_options = OpenOptions::new();
            log_options.create(true).append(true).write(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                log_options.mode(0o600);
            }
            let log_file = log_options.open(&log_path)?;
            let log_stderr = log_file.try_clone()?;

            let mut command = Command::new(&executable);
            command
                .current_dir(&data_dir)
                .env("NETREGRESS_PACKAGED", "1")
                .env("NETREGRESS_HOST", "127.0.0.1")
                .env("NETREGRESS_PORT", port.to_string())
                .env("NETREGRESS_AUTH_REQUIRED", "1")
                .env("NETREGRESS_AUTH_USERS_JSON", "")
                .env("NETREGRESS_USER_DATA_DIR", &data_dir)
                .env("NETREGRESS_LOCAL_DIR", &data_dir)
                .env("NETREGRESS_CONFIG_DIR", &config_dir)
                .env("NETREGRESS_LOG_DIR", &logs_dir)
                .env("NETREGRESS_RUNTIME_DIR", &runtime_dir)
                .env("NETREGRESS_RESULTS_DIR", &results_dir)
                .env("NETREGRESS_PROCESS_DIR", &process_dir)
                .env("NETREGRESS_DATABASE_PATH", results_dir.join("test_results.db"))
                .env("NETREGRESS_SESSION_COOKIE_SECURE", "1")
                .env("NETREGRESS_SESSION_COOKIE_SAMESITE", "None")
                .env("PYTHONNOUSERSITE", "1")
                .stdin(Stdio::null())
                .stdout(Stdio::from(log_file))
                .stderr(Stdio::from(log_stderr));

            let mut child = command.spawn()?;
            if let Err(error) = wait_for_backend(&mut child, port) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
            app.manage(BackendState {
                base_url: format!("http://127.0.0.1:{port}"),
                child: Mutex::new(Some(child)),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build NetRegress desktop application");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            if let Some(state) = handle.try_state::<BackendState>() {
                stop_backend(&state);
            }
        }
    });
}
