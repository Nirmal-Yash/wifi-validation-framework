from lib.services.resource_lock import ResourceLockError,ResourceLockManager

def test_exclusive_lock(tmp_path):
    manager=ResourceLockManager(tmp_path)
    first=manager.acquire("lab:one","owner-1")
    try:
        try:
            manager.acquire("lab:one","owner-2")
            assert False
        except ResourceLockError:
            pass
    finally:
        first.release()
