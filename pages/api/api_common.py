"""
pages/api/api_common.py
-----------------------
Base class for ALL API Page Objects (service clients).
Wraps the requests library with:
  - Allure step decoration for every call
  - Automatic retry on server errors
  - Response validation helpers
  - Token / auth management
  - Schema validation (jsonschema)
  - Request/response logging to Allure
"""
import json
import time
import allure
import logging
from typing import Any, Optional
import requests
from requests import Response, Session

from config.config_loader import CFG

log = logging.getLogger(__name__)


class APICommon:
    """
    Generic REST API client base class.
    Extend this for each service/microservice.

    Usage:
        class UserService(APICommon):
            def get_user(self, user_id):
                return self.get(f"/users/{user_id}")
    """

    def __init__(self, base_url: str = None, token: str = None):
        self.base_url = (base_url or CFG.api_base_url).rstrip("/")
        self.session  = Session()
        self.session.headers.update(CFG.api_headers)
        if token:
            self.set_auth_token(token)

    # ================================================================
    # AUTH
    # ================================================================
    def set_auth_token(self, token: str, scheme: str = "Bearer"):
        self.session.headers.update({"Authorization": f"{scheme} {token}"})
        log.info("[API] Auth token set.")

    def set_basic_auth(self, username: str, password: str):
        self.session.auth = (username, password)

    def set_header(self, key: str, value: str):
        self.session.headers[key] = value

    def clear_auth(self):
        self.session.headers.pop("Authorization", None)
        self.session.auth = None

    # ================================================================
    # CORE HTTP METHODS
    # ================================================================
    @allure.step("GET {endpoint}")
    def get(self, endpoint: str, params: dict = None, **kwargs) -> Response:
        return self._request("GET", endpoint, params=params, **kwargs)

    @allure.step("POST {endpoint}")
    def post(self, endpoint: str, body: Any = None, **kwargs) -> Response:
        return self._request("POST", endpoint, json=body, **kwargs)

    @allure.step("PUT {endpoint}")
    def put(self, endpoint: str, body: Any = None, **kwargs) -> Response:
        return self._request("PUT", endpoint, json=body, **kwargs)

    @allure.step("PATCH {endpoint}")
    def patch(self, endpoint: str, body: Any = None, **kwargs) -> Response:
        return self._request("PATCH", endpoint, json=body, **kwargs)

    @allure.step("DELETE {endpoint}")
    def delete(self, endpoint: str, **kwargs) -> Response:
        return self._request("DELETE", endpoint, **kwargs)

    @allure.step("HEAD {endpoint}")
    def head(self, endpoint: str, **kwargs) -> Response:
        return self._request("HEAD", endpoint, **kwargs)

    # ================================================================
    # INTERNAL: request with retry + allure logging
    # ================================================================
    def _request(self, method: str, endpoint: str, **kwargs) -> Response:
        url     = self._build_url(endpoint)
        timeout = kwargs.pop("timeout", CFG.api_timeout)
        retries = CFG.api_max_retries
        attempt = 0
        print("a-a-a-a",url)

        while attempt <= retries:
            try:
                response = self.session.request(
                    method, url, timeout=timeout, **kwargs
                )
                self._attach_to_allure(method, url, kwargs, response)

                if response.status_code in CFG.api_retry_statuses and attempt < retries:
                    log.warning(
                        f"[API] {method} {url} → {response.status_code}, "
                        f"retrying ({attempt+1}/{retries})…"
                    )
                    attempt += 1
                    time.sleep(CFG.retry_delay)
                    continue

                log.info(f"[API] {method} {url} → {response.status_code} ({response.elapsed.total_seconds():.2f}s)")
                return response

            except requests.exceptions.ConnectionError as e:
                log.error(f"[API] Connection error: {e}")
                if attempt < retries:
                    attempt += 1
                    time.sleep(CFG.retry_delay)
                    continue
                raise
            except requests.exceptions.Timeout:
                log.error(f"[API] Timeout after {timeout}s: {method} {url}")
                raise

        return response   # fallback

    def _build_url(self, endpoint: str) -> str:
        if endpoint.startswith("http"):
            return endpoint
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _attach_to_allure(self, method: str, url: str, req_kwargs: dict, response: Response):
        """Attach full request/response details to Allure report."""
        # Request body
        req_body = req_kwargs.get("json") or req_kwargs.get("data", "")
        if req_body:
            allure.attach(
                json.dumps(req_body, indent=2) if isinstance(req_body, (dict, list)) else str(req_body),
                name=f"Request Body [{method} {url}]",
                attachment_type=allure.attachment_type.JSON,
            )

        # Response body
        try:
            resp_body = json.dumps(response.json(), indent=2)
            attach_type = allure.attachment_type.JSON
        except Exception:
            resp_body = response.text
            attach_type = allure.attachment_type.TEXT

        allure.attach(
            resp_body,
            name=f"Response [{response.status_code}] {method} {url}",
            attachment_type=attach_type,
        )

        # Response headers
        allure.attach(
            json.dumps(dict(response.headers), indent=2),
            name="Response Headers",
            attachment_type=allure.attachment_type.JSON,
        )

    # ================================================================
    # RESPONSE ASSERTIONS
    # ================================================================
    @allure.step("Assert status code: {expected}")
    def assert_status(self, response: Response, expected: int):
        actual = response.status_code
        assert actual == expected, (
            f"Expected HTTP {expected}, got {actual}.\n"
            f"URL: {response.url}\nBody: {response.text[:500]}"
        )
        log.info(f"[API] ✓ Status {actual} == {expected}")

    @allure.step("Assert response contains key: {key}")
    def assert_json_key(self, response: Response, key: str):
        body = response.json()
        assert key in body, f"Key '{key}' not found in response: {list(body.keys())}"

    @allure.step("Assert response key value")
    def assert_json_value(self, response: Response, key: str, expected: Any):
        body = response.json()
        actual = body.get(key)
        assert actual == expected, f"response['{key}'] expected '{expected}', got '{actual}'"

    @allure.step("Assert response is list")
    def assert_is_list(self, response: Response):
        assert isinstance(response.json(), list), \
            f"Expected list, got {type(response.json())}"

    @allure.step("Assert response list not empty")
    def assert_list_not_empty(self, response: Response):
        data = response.json()
        assert isinstance(data, list) and len(data) > 0, "Response list is empty."

    @allure.step("Assert response time < {max_ms}ms")
    def assert_response_time(self, response: Response, max_ms: int):
        elapsed_ms = response.elapsed.total_seconds() * 1000
        assert elapsed_ms < max_ms, \
            f"Response time {elapsed_ms:.0f}ms exceeds limit {max_ms}ms"

    def assert_schema(self, response: Response, schema: dict):
        """Validate response body against a JSON schema."""
        try:
            import jsonschema
            jsonschema.validate(instance=response.json(), schema=schema)
            log.info("[API] ✓ Schema validation passed")
        except ImportError:
            log.warning("[API] jsonschema not installed — skipping schema validation")
        except Exception as e:
            raise AssertionError(f"Schema validation failed: {e}")

    # ================================================================
    # CONVENIENCE EXTRACTORS
    # ================================================================
    def json(self, response: Response) -> Any:
        return response.json()

    def text(self, response: Response) -> str:
        return response.text

    def status_code(self, response: Response) -> int:
        return response.status_code

    def header(self, response: Response, name: str) -> Optional[str]:
        return response.headers.get(name)

    def elapsed_ms(self, response: Response) -> float:
        return response.elapsed.total_seconds() * 1000

    # ================================================================
    # FILE UPLOAD
    # ================================================================
    @allure.step("Upload file to: {endpoint}")
    def upload_file(self, endpoint: str, file_path: str, field_name: str = "file") -> Response:
        with open(file_path, "rb") as f:
            return self._request(
                "POST", endpoint,
                files={field_name: f},
                json=None,     # override default JSON header
            )

    # ================================================================
    # DOWNLOAD
    # ================================================================
    @allure.step("Download from: {endpoint}")
    def download(self, endpoint: str, save_path: str) -> str:
        response = self.get(endpoint)
        with open(save_path, "wb") as f:
            f.write(response.content)
        log.info(f"[API] Downloaded to {save_path}")
        return save_path

    # ================================================================
    # GRAPHQL HELPER
    # ================================================================
    @allure.step("GraphQL query")
    def graphql(self, endpoint: str, query: str, variables: dict = None) -> Response:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        return self.post(endpoint, body=payload)
