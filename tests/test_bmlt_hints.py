import base64

from app.scraping.bmlt_hints import bmlt_endpoint_from_html


def test_bmlt_endpoint_from_html_decodes_base64_data_script() -> None:
    script = """
    crouton = new Crouton({
      "root_server": "https:\\/\\/tomato.bmltenabled.org\\/main_server",
      "service_body": ["631"],
      "recurse_service_bodies": true
    });
    """
    encoded = base64.b64encode(script.encode()).decode()
    html = f'<script src="data:text/javascript;base64,{encoded}"></script>'

    endpoint = bmlt_endpoint_from_html(html)

    assert endpoint == (
        "https://tomato.bmltenabled.org/main_server/client_interface/json/?"
        "switcher=GetSearchResults&services%5B%5D=631&recursive=1"
    )


def test_bmlt_endpoint_from_html_handles_numeric_service_ids_and_recurse() -> None:
    html = """
    <script>
    crouton = new Crouton({
      "root_server": "https:\\/\\/aggregator.bmltenabled.org\\/main_server",
      "service_body": [803],
      "recurse_service_bodies": 1
    });
    </script>
    """

    endpoint = bmlt_endpoint_from_html(html)

    assert endpoint == (
        "https://aggregator.bmltenabled.org/main_server/client_interface/json/?"
        "switcher=GetSearchResults&services%5B%5D=803&recursive=1"
    )
