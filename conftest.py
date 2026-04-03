"""
conftest.py — Master fixture file for PW_Automation Framework
==============================================================
Fixtures provided:
  Web    : playwright_instance, browser, page (with named video)
  Mobile : android_driver, ios_driver
  API    : api_session
  Users  : buyer_user, seller_user, admin_user, api_user, mobile_user
  Util   : logger, worker_id
Hooks:
  - Screenshot + video + log attached to Allure on failure
  - Email notification on failure and session end
  - User pool released on test teardown
"""
import os, shutil, re, logging
import allure
import pytest
from datetime import datetime
from playwright.sync_api import sync_playwright

from config.config_loader import CFG
from util.logger_util    import get_logger
from util.email_util     import send_failure_email, send_summary_email
from util.user_manager   import acquire_user, release_user, reset_all_users

_failed_tests: list[dict] = []

# ============================================================
# SESSION SETUP
# ============================================================
@pytest.fixture(scope="session", autouse=True)
def session_setup():
    """Clean logs + reset user pool at session start."""
    if not CFG.retain_logs and os.path.exists(CFG.log_dir):
        shutil.rmtree(CFG.log_dir)
    os.makedirs(CFG.log_dir, exist_ok=True)
    os.makedirs(CFG.allure_results_dir, exist_ok=True)
    reset_all_users()   # unlock any users left from a crashed run
    yield


def pytest_runtest_setup(item):
    worker_id = getattr(item.config, "workerinput", {}).get("workerid", "single")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with allure.step(f"🕒 [{worker_id}] START {item.name} at {now}"):
        pass




# ============================================================
# WORKER ID (pytest-xdist safe)
# ============================================================
@pytest.fixture(scope="session")
def worker_id(request):
    return getattr(request.config, "workerinput", {}).get("workerid", "main")

# ============================================================
# WEB FIXTURES
# ============================================================
@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p

@pytest.fixture(scope="session")
def browser(playwright_instance):
    launcher = getattr(playwright_instance, CFG.browser_name)
    b = launcher.launch(headless=CFG.headless, slow_mo=CFG.slow_mo)
    yield b
    b.close()

@pytest.fixture(scope="function")
def page(request, browser):
    """
    Browser page fixture with:
      - Video recording (file named <test_name>_<timestamp>.webm)
      - Screenshot on failure
      - Video attached to Allure on failure
    """
    test_name   = _safe_name(request.node.name)
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_dir   = os.path.join(CFG.allure_results_dir, "videos")
    os.makedirs(video_dir, exist_ok=True)

    context = browser.new_context(
        viewport            = CFG.viewport,
        record_video_dir    = video_dir,
        record_video_size   = CFG.viewport,
    )
    context.set_default_timeout(CFG.timeout)
    pg = context.new_page()

    if request.cls:
        request.cls.driver = pg

    yield pg

    # ---- teardown: capture video path BEFORE context.close() ----
    pg.close()
    video_path = None
    try:
        raw_path = pg.video.path() if pg.video else None
        if raw_path and os.path.exists(raw_path):
            # Rename to include test name
            named_path = os.path.join(video_dir, f"{test_name}_{timestamp}.webm")
            os.rename(raw_path, named_path)
            video_path = named_path
    except Exception:
        pass
    context.close()
    request.node._video_path = video_path

# ============================================================
# MOBILE FIXTURES
# ============================================================
@pytest.fixture(scope="function")
def android_driver(request):
    """Appium driver for Android. Skipped if appium-python-client not installed."""
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

    except ImportError:
        pytest.skip("appium-python-client not installed")

    options = UiAutomator2Options()

    options.platform_name = CFG.android_caps["platform_name"]
    options.automation_name= CFG.android_caps['automation_name']
    options.device_name = CFG.android_caps["device_name"]
    options.udid = CFG.android_caps["device_name"]
    options.app_package = CFG.android_caps["app_package"]
    options.app_activity = CFG.android_caps["app_activity"]
    options.no_reset = True


    # caps = {
    #     "platformName":   ,
    #     "automationName": CFG.android_caps["automation_name"],
    #     "deviceName":     CFG.android_caps["device_name"],
    #     "appPackage":     CFG.android_caps["app_package"],
    #     "appActivity":    CFG.android_caps["app_activity"],
    #     "noReset":        CFG.android_caps["no_reset"],
    # }
    # print(f"----{CFG.appium_server}----{caps}")
    driver = webdriver.Remote(CFG.appium_server, options=options)
    if request.cls:
        request.cls.driver = driver
    yield driver
    driver.quit()

@pytest.fixture(scope="function")
def ios_driver(request):
    """Appium driver for iOS. Skipped if appium-python-client not installed."""
    try:
        from appium import webdriver as appium_webdriver
    except ImportError:
        pytest.skip("appium-python-client not installed")

    caps = {k: v for k, v in {
        "platformName":   CFG.ios_caps["platform_name"],
        "automationName": CFG.ios_caps["automation_name"],
        "deviceName":     CFG.ios_caps["device_name"],
        "platformVersion":CFG.ios_caps["platform_version"],
        "udid":           CFG.ios_caps.get("udid", ""),
        "bundleId":       CFG.ios_caps["bundle_id"],
        "wdaLocalPort":   CFG.ios_caps["wda_local_port"],
        "noReset":        CFG.ios_caps["no_reset"],
    }.items() if v}
    driver = appium_webdriver.Remote(CFG.appium_server, caps)
    if request.cls:
        request.cls.driver = driver
    yield driver
    driver.quit()

# ============================================================
# USER POOL FIXTURES (role-based)
# ============================================================
def _user_fixture(role: str):
    @pytest.fixture(scope="function")
    def _fixture(worker_id):
        print("collect user for ",role)
        user = acquire_user(role, worker_id=worker_id)
        yield user
        print("release user for ", role)
        release_user(user)
    return _fixture

buyer_user   = _user_fixture("buyer")
seller_user  = _user_fixture("seller")
admin_user   = _user_fixture("admin")
api_user     = _user_fixture("api_user")
mobile_user  = _user_fixture("mobile_user")
viewer_user  = _user_fixture("viewer")

# ============================================================
# LOGGER FIXTURE
# ============================================================
@pytest.fixture(scope="function")
def logger(request):
    log = get_logger(request.node.name, CFG.log_dir, CFG.log_level)
    request.node._log_file = os.path.join(CFG.log_dir, f"{request.node.name}.log")
    yield log
    for h in log.handlers[:]:
        h.close(); log.removeHandler(h)

# ============================================================
# ALLURE HOOK — screenshot + video + log on failure
# ============================================================
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report  = outcome.get_result()

    if report.when == "call":
        # Attach log
        log_file = getattr(item, "_log_file", None)
        if log_file and os.path.exists(log_file) and CFG.attach_logs:
            with open(log_file, "rb") as f:
                allure.attach(f.read(), name="Test Log",
                              attachment_type=allure.attachment_type.TEXT)

        if report.failed:
            # Screenshot
            try:
                drv = getattr(item.cls, "driver", None) if item.cls else None
                if drv and CFG.attach_screenshots:
                    # Playwright page
                    if hasattr(drv, "screenshot"):
                        allure.attach(drv.screenshot(),
                                      name=f"Screenshot — {item.name}",
                                      attachment_type=allure.attachment_type.PNG)
                    # Appium driver
                    elif hasattr(drv, "get_screenshot_as_png"):
                        allure.attach(drv.get_screenshot_as_png(),
                                      name=f"Screenshot — {item.name}",
                                      attachment_type=allure.attachment_type.PNG)
            except Exception as e:
                logging.warning(f"[conftest] Screenshot failed: {e}")

            # Video
            video_path = getattr(item, "_video_path", None)
            if video_path and os.path.exists(video_path) and CFG.attach_videos:
                with open(video_path, "rb") as vf:
                    allure.attach(vf.read(),
                                  name=f"Video — {item.name}",
                                  attachment_type=allure.attachment_type.WEBM)

            _failed_tests.append({
                "test":   item.name,
                "nodeid": item.nodeid,
                "log":    log_file,
                "video":  video_path,
            })

            if CFG.email_enabled and CFG.send_on in ("failure", "always"):
                try:
                    send_failure_email(item.name, log_file)
                except Exception as e:
                    logging.warning(f"[conftest] Email failed: {e}")

# ============================================================
# SESSION FINISH — summary email
# ============================================================
def pytest_sessionfinish(session, exitstatus):
    total  = session.testscollected
    failed = len(_failed_tests)
    passed = total - failed
    if CFG.email_enabled and CFG.send_on in ("always", "failure") and failed > 0:
        try:
            send_summary_email(total, passed, failed, _failed_tests)
        except Exception as e:
            logging.warning(f"[conftest] Summary email failed: {e}")

# ============================================================
# HELPER
# ============================================================
def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)[:60]
