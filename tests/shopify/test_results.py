from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import GraphQLError, Ok, Uncertain, classify_payload, user_errors


def test_payload_with_errors_is_graphql_error() -> None:
    assert classify_payload({"errors": [{"message": "x"}]}) == GraphQLError(({"message": "x"},))


def test_empty_errors_list_is_ok() -> None:
    assert classify_payload({"errors": [], "a": 1}) == Ok({"errors": [], "a": 1})


def test_data_wrapper_is_unwrapped() -> None:
    assert classify_payload({"data": {"a": 1}}) == Ok({"a": 1})


def test_null_data_is_uncertain() -> None:
    assert isinstance(classify_payload({"data": None}), Uncertain)


def test_non_object_is_uncertain() -> None:
    assert isinstance(classify_payload([1]), Uncertain)


def test_user_errors_found_in_any_payload() -> None:
    data: JsonObject = {
        "orderUpdate": {"userErrors": [{"message": "bad"}]},
        "other": {"userErrors": []},
    }
    assert user_errors(data) == ({"message": "bad"},)
