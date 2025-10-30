from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

TOPIC_FILTER_PARAMS_SPECTACULAR = [
    OpenApiParameter("language_abbr", str, OpenApiParameter.QUERY, description="Abbreviation. Aliases: abbr/language_code/code/lang"),
    OpenApiParameter("abbr", str, OpenApiParameter.QUERY),
    OpenApiParameter("language_code", str, OpenApiParameter.QUERY),
    OpenApiParameter("code", str, OpenApiParameter.QUERY),
    OpenApiParameter("lang", str, OpenApiParameter.QUERY),
    OpenApiParameter("language_id", int, OpenApiParameter.QUERY),
    OpenApiParameter("page", int, OpenApiParameter.QUERY),
    OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
]

TOPIC_BY_LANGUAGE_PARAMS = [
    OpenApiParameter(
        name="language_abbr",
        type=str,
        location=OpenApiParameter.QUERY,
        description='Abbreviation. Aliases: abbr | language_code | code | lang.',
    ),
    OpenApiParameter(name="language_id",   type=int, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="page",          type=int, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="page_size",     type=int, location=OpenApiParameter.QUERY),
]