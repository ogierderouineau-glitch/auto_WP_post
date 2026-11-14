from types import SimpleNamespace

from backend.app.api.step_03_container import keyword_source_status


def test_status_reports_only_what_the_configuration_enables(tmp_path):
    key = tmp_path / "key.json"
    key.write_text("{}")
    full = SimpleNamespace(search_console_property="https://a.example/", search_console_credentials_file=str(key),
                           service_link_category="service")
    assert keyword_source_status(full) == {
        "search_console_configured": True,
        "search_console_credentials_file_found": True,
        "service_link_category_configured": True,
    }
    missing_file = SimpleNamespace(search_console_property="https://a.example/",
                                   search_console_credentials_file=str(tmp_path / "nope.json"), service_link_category="")
    assert keyword_source_status(missing_file) == {
        "search_console_configured": True,
        "search_console_credentials_file_found": False,
        "service_link_category_configured": False,
    }
    assert not any(keyword_source_status(SimpleNamespace(search_console_property="", search_console_credentials_file="",
                                                         service_link_category="")).values())
