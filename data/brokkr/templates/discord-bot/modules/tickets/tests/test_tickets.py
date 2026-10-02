from cogs.tickets import nom_ticket


def test_nom_ticket():
    assert nom_ticket("Astrid", "Problème de rôle !") == "ticket-astrid-probleme-de-role"
    assert len(nom_ticket("x", "y" * 300)) == 100
