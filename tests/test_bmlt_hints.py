from app.scraping.bmlt_hints import bmlt_endpoint_from_html


def test_bmlt_endpoint_from_crouton_html_includes_service_filters() -> None:
    html = r'''
    crouton = new Crouton({
      "root_server":"https:\/\/bmlt.example.org\/main_server",
      "service_body":["1006","1007"]
    });
    '''

    endpoint = bmlt_endpoint_from_html(html)

    assert endpoint == (
        "https://bmlt.example.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services%5B%5D=1006&services%5B%5D=1007"
    )


def test_bmlt_endpoint_from_crouton_html_includes_recursive_flag() -> None:
    html = r'''
    crouton = new Crouton({
      "root_server":"https:\/\/bmlt.example.org\/main_server",
      "service_body":["1052"],
      "recurse_service_bodies":true
    });
    '''

    endpoint = bmlt_endpoint_from_html(html)

    assert endpoint == (
        "https://bmlt.example.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services%5B%5D=1052&recursive=1"
    )


def test_bmlt_endpoint_prefers_custom_query_when_present() -> None:
    html = r'''
    crouton = new Crouton({
      "root_server":"https:\/\/bmlt.example.org\/main_server",
      "custom_query":"services[]=1067&formats[]=55&formats_comparison_operator=OR",
      "service_body":["1"]
    });
    '''

    endpoint = bmlt_endpoint_from_html(html)

    assert endpoint == (
        "https://bmlt.example.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services%5B%5D=1067&formats%5B%5D=55"
        "&formats_comparison_operator=OR"
    )


def test_bmlt_endpoint_from_html_returns_none_without_root_server() -> None:
    assert bmlt_endpoint_from_html("<html></html>") is None
