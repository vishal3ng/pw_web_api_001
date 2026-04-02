"""
config_loader.py
----------------
Single source of truth for all framework configuration.
Reads config/config.yaml, resolves ${ENV_VAR} placeholders,
and exposes a typed CFG singleton used everywhere.
"""
import os, re, yaml
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

def _resolve(value="aa"):
    # if not isinstance(value, str):
    if value:
        return value
    def _sub(m):
        k = m.group(1)
        v = os.environ.get(k)
        if v is None:
            raise EnvironmentError(f"[Config] Required env var '{k}' not set. Add to .env or CI Secrets.")
        return v
    return re.sub(r"\$\{(\w+)\}", _sub, value)

def _deep(obj):
    if isinstance(obj, dict):  return {k: _deep(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_deep(i) for i in obj]
    if isinstance(obj, str):   return _resolve(obj)
    return obj

class Config:
    _inst = None
    def __new__(cls):
        if not cls._inst:
            cls._inst = super().__new__(cls)
            cls._inst._load()
        return cls._inst

    def _load(self):
        raw = yaml.safe_load(_CONFIG_PATH.read_text())
        env = os.environ.get("ENVIRONMENT", raw.get("environment", "staging"))
        self._env  = env
        self._raw  = raw

        # URLs
        u = raw["urls"].get(env, raw["urls"]["staging"])
        self.base_url     = _resolve(u["base_url"])
        self.api_base_url = _resolve(u["api_base_url"])

        # Users
        self.user_pool_file        = raw["users"]["pool_file"]
        self.user_lock_timeout     = int(raw["users"]["lock_timeout_seconds"])

        # Browser
        b = raw["browser"]
        self.browser_name = b["name"]
        self.headless     = os.environ.get("HEADLESS", str(b["headless"])).lower() == "true"
        print('brbrbr',os.environ.get("HEADLESS", str(b["headless"])).lower())
        self.slow_mo      = int(b["slow_mo"])
        self.timeout      = int(b["timeout"])
        self.viewport     = b["viewport"]
        self.video        = b["video"]

        # Mobile
        self.appium_server = raw["mobile"]["appium_server"]
        self.android_caps  = raw["mobile"]["android"]
        # self.ios_caps      = _deep(raw["mobile"]["ios"])

        # API
        a = raw["api"]
        self.api_timeout        = int(a["default_timeout"])
        self.api_retry_statuses = a["retry_on_status"]
        self.api_max_retries    = int(a["max_retries"])
        self.api_headers        = a["headers"]

        # Allure
        al = raw["allure"]
        self.allure_results_dir     = al["results_dir"]
        self.allure_report_dir      = al["report_dir"]
        self.attach_logs            = bool(al["attach_logs"])
        self.attach_screenshots     = bool(al["attach_screenshots"])
        self.attach_videos          = bool(al["attach_videos"])

        # Email — only resolve secrets if enabled
        em = raw["email"]
        self.email_enabled   = bool(em["enabled"])
        self.email_sender    = _resolve(em["sender"])    if self.email_enabled else ""
        self.email_password  = _resolve(em["password"])  if self.email_enabled else ""
        self.email_receivers = em["receivers"]
        self.smtp_host       = em["smtp_host"]
        self.smtp_port       = int(em["smtp_port"])
        self.send_on         = em["send_on"]

        # Logging
        lg = raw["logging"]
        self.log_level   = lg["level"]
        self.log_dir     = lg["log_dir"]
        self.retain_logs = bool(lg["retain_logs"])

        # Retry
        r = raw["retry"]
        self.max_retries  = int(r["max_retries"])
        self.retry_delay  = int(r["delay_seconds"])

        # CI
        self.parallel_workers = int(raw["ci"]["parallel_workers"])

    def __repr__(self):
        return f"<Config env={self._env} base_url={self.base_url}>"

CFG = Config()
