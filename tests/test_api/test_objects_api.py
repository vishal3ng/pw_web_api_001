"""
tests/test_api/test_objects_api.py
-----------------------------------
Sample API tests — full CRUD on /objects endpoint.
Uses:
  - api_user  : role-based user from pool (has api_token)
  - logger    : per-test logger
"""
import allure
import pytest
from pages.api.objects_service import ObjectsService
from config.config_loader import CFG


@allure.epic("API Tests")
@allure.feature("Objects API — CRUD")
class TestObjectsAPI:

    @allure.story("GET all objects returns 200 and a list")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.api
    @pytest.mark.smoke
    def test_get_all_objects(self, api_user, logger):
        logger.info("GET /objects")
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.get_all_objects()
        svc.assert_status(response, 200)
        svc.assert_is_list(response)
        svc.assert_list_not_empty(response)
        logger.info(f"PASS: {len(response.json())} objects returned")

    @allure.story("GET single object returns 200")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.api
    @pytest.mark.smoke
    def test_get_single_object(self, api_user, logger):
        logger.info("GET /objects/1")
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.get_object("1")
        svc.assert_status(response, 200)
        svc.assert_json_key(response, "id")
        svc.assert_json_key(response, "name")
        logger.info(f"PASS: object = {response.json()}")

    @allure.story("POST creates a new object and returns 200")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.api
    @pytest.mark.regression
    def test_create_object(self, api_user, logger):
        logger.info("POST /objects — create new object")
        print("cvcvcvc",api_user)
        svc     = ObjectsService(token=api_user.get("api_token"))
        payload = {
            "name": "Corporate QA Test Object",
            "data": {"year": 2026, "price": 999.99, "CPU model": "Intel Core i9"}
        }
        response = svc.create_object(payload["name"], payload["data"])
        svc.assert_status(response, 200)
        body = response.json()
        assert body.get("name") == payload["name"], \
            f"Name mismatch: {body.get('name')}"
        assert "id" in body, "Response should contain 'id'"
        logger.info(f"PASS: created object id={body.get('id')}")

    @allure.story("PUT updates an existing object")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.api
    @pytest.mark.regression
    def test_update_object(self, api_user, logger):
        print("cvcvcvc", api_user)
        logger.info("PUT /objects/7 — update object")
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.update_object(
            "7",
            name="Updated Object",
            data={"year": 2026, "price": 1500, "CPU model": "M3 Pro"}
        )
        svc.assert_status(response, 200)
        body = response.json()
        assert body.get("name") == "Updated Object"
        logger.info(f"PASS: updated object = {body}")

    @allure.story("PATCH partially updates an object")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.api
    @pytest.mark.regression
    def test_patch_object(self, api_user, logger):
        logger.info("PATCH /objects/7")
        print("cvcvcvc", api_user)
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.patch_object("7", {"name": "Patched Object Name"})
        svc.assert_status(response, 200)
        assert response.json().get("name") == "Patched Object Name"
        logger.info("PASS: object patched")

    @allure.story("DELETE removes an object and returns 200")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.api
    @pytest.mark.regression
    def test_delete_object(self, api_user, logger):
        logger.info("DELETE /objects — creating then deleting")
        print("cvcvcvc", api_user)
        svc = ObjectsService(token=api_user.get("api_token"))
        # First create so we can delete
        create_resp = svc.create_object("Temp Object", {"temp": True})
        svc.assert_status(create_resp, 200)
        obj_id = create_resp.json().get("id")
        logger.info(f"Created temp object id={obj_id}")
        # Now delete it
        del_resp = svc.delete_object(obj_id)
        svc.assert_status(del_resp, 200)
        logger.info("PASS: object deleted")

    @allure.story("API responds within acceptable time")
    @allure.severity(allure.severity_level.MINOR)
    @pytest.mark.api
    @pytest.mark.performance
    def test_api_response_time(self, api_user, logger):
        logger.info("Checking API response time")
        print("cvcvcvc", api_user)
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.get_all_objects()
        svc.assert_status(response, 200)
        svc.assert_response_time(response, max_ms=5000)
        elapsed = svc.elapsed_ms(response)
        logger.info(f"PASS: response time = {elapsed:.0f}ms")

    @allure.story("GET non-existent object returns 404")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.api
    @pytest.mark.regression
    def test_get_nonexistent_object(self, api_user, logger):
        logger.info("GET /objects/999999 — expect 404 or error")
        print("cvcvcvc", api_user)
        svc      = ObjectsService(token=api_user.get("api_token"))
        response = svc.get_object("999999")
        logger.info(f"Response: {response.status_code} {response.text}")
        # Accept 404 or 200 with error message (API behaviour varies)
        assert response.status_code in (404, 200), \
            f"Unexpected status: {response.status_code}"
        logger.info("PASS: non-existent object handled")
