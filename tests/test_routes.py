from __future__ import annotations

from guildbridge.routes import canonical_provider_names, structure_route_document, structure_routes_table


def test_explicit_route_names_are_canonicalized_and_deduplicated() -> None:
    assert canonical_provider_names([" Stoat ", "discord", "stoat", " "]) == ["discord", "stoat"]


def test_default_route_names_use_the_registered_provider_registry() -> None:
    names = canonical_provider_names()

    assert "discord" in names
    assert "stoat" in names
    assert names == sorted(names)


def test_route_document_describes_same_provider_and_multi_target_routes() -> None:
    document = structure_route_document(["discord", "stoat"])

    assert document["provider_count"] == 2
    assert document["route_count"] == 4
    assert document["multi_target"]["supported"] is True
    assert {route["same_provider_clone"] for route in document["routes"]} == {False, True}
    assert all(route["multi_target"] is True for route in document["routes"])


def test_route_table_includes_the_canonical_provider_matrix() -> None:
    table = structure_routes_table(["stoat", "discord"])

    assert "Providers: discord, stoat" in table
    assert "Routes: 4" in table
    assert "- discord -> discord, stoat" in table
