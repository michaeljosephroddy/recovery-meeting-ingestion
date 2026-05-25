from app.adapters.static_html import StaticHtmlAdapter
from app.scraping.na_brazil import raw_records_from_cade_o_grupo_response
from app.sources.registry import AdapterType, Source, SourceType


def test_na_brazil_cade_o_grupo_response_extracts_occurrence_records() -> None:
    source = Source(
        id="na-br-sp",
        fellowship="na",
        name="Brazil Region",
        url="https://www.na.org.br/grupos",
        country="Brazil",
        region="Sao Paulo",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )
    response = """
    {}||
    <table id="copy0">
      <tr><td colspan="2"><svg><title>Reunião Verificada</title></svg>Grupo 12 Passos</td></tr>
      <tr>
        <td>Dom</td>
        <td>20:00 às 22:00 (Tempo de Partilha, Acesso Total a Cadeirantes)</td>
      </tr>
      <tr>
        <td>Ter</td>
        <td>19:30 às 21:00 (Aberta para visitantes)</td>
      </tr>
      <tr>
        <td colspan="2">
          Praça da Bandeira S/N, Centro<br>
          Presidente Prudente / São Paulo - 19010250
          <div>Salas sob o Viaduto</div>
          Funciona nos feriados.
        </td>
      </tr>
    </table>
    <a href="https://www.google.com/maps/search/?api=1&amp;query=-22.1235719,-51.3829359">Mapa</a>
    """

    records = raw_records_from_cade_o_grupo_response(source, response)

    assert len(records) == 2
    first = records[0].payload
    assert first["name"] == "Grupo 12 Passos"
    assert first["day"] == "domingo"
    assert first["time"] == "20:00"
    assert first["end_time"] == "22:00"
    assert first["city"] == "Presidente Prudente"
    assert first["postal_code"] == "19010250"
    assert first["latitude"] == -22.1235719
    assert first["longitude"] == -51.3829359

    candidate = StaticHtmlAdapter(source).normalize(records[0])
    assert candidate.occurrences[0].day_of_week == 0
    assert candidate.occurrences[0].end_time_local is not None
    assert candidate.latitude == -22.1235719
    assert candidate.postal_code == "19010250"


def test_litoral_norte_gaucho_source_filters_state_feed_to_local_groups() -> None:
    source = Source(
        id="na-5f238c81d49f",
        fellowship="na",
        name="Litoral Norte Gaucho Area",
        url="https://sites.google.com/view/csalitoral/membros-e-visitantes/reunioes-grupos",
        country="Brazil",
        region="Rio Grande do Sul",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )
    response = """
    {}||
    <table id="copy0">
      <tr><td colspan="2">Grupo Fênix</td></tr>
      <tr><td>Seg</td><td>19:00 às 20:00 (Aberta)</td></tr>
      <tr><td colspan="2">
        Rua Viola 715, Jardim Beira Mar<br>
        Capão da Canoa / Rio Grande do Sul - 95555000
      </td></tr>
    </table>
    <table id="copy1">
      <tr><td colspan="2">Grupo Mente Aberta</td></tr>
      <tr><td>Seg</td><td>19:00 às 20:00 (Aberta)</td></tr>
      <tr><td colspan="2">
        Rua Arroio Grande 50<br>
        Porto Alegre / Rio Grande do Sul - 90000000
      </td></tr>
    </table>
    """

    records = raw_records_from_cade_o_grupo_response(source, response)

    assert len(records) == 1
    assert records[0].payload["name"] == "Grupo Fênix"
    assert records[0].payload["city"] == "Capão da Canoa"
