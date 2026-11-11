// Set the explicit first-run theme before application styles are loaded.
try {
  const savedTheme = window.localStorage.getItem("netregress-theme");
  document.documentElement.dataset.theme = savedTheme === "dark" ? "dark" : "light";
} catch {
  document.documentElement.dataset.theme = "light";
}
