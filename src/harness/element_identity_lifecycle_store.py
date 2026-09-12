"""Connection-owned lifecycle planning shared by apply and preview."""

from harness import element_identity_lifecycle as lifecycle


def plan_changes(connection, store, spec_id, changes):
    changes, _, labels = lifecycle.request(changes)
    for kind in {label.split("-", 1)[0] for label in labels}:
        store._high_water(connection, spec_id, kind)
    planned, links = [], []
    for change in changes:
        if type(change) is lifecycle.ElementCreate:
            planned.append(store._creation(connection, spec_id, change))
        elif type(change) is lifecycle.ElementAdopt:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, None,
                subject=change.subject, content=change.content, adopt=True,
            ))
        elif type(change) is lifecycle.ElementRevision:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                subject=change.subject, content=change.content,
            ))
        elif type(change) is lifecycle.ElementRetirement:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                status="retired", reason=change.reason,
            ))
        else:
            for label, expected in change.predecessors:
                planned.append(store._existing_change(
                    connection, spec_id, label, expected,
                    status="superseded", reason=change.reason,
                ))
            for successor in change.successors:
                planned.append(store._creation(connection, spec_id, successor))
            links.extend(
                (spec_id, label, expected, successor.element_id, "1", change.kind, change.reason)
                for label, expected in change.predecessors
                for successor in change.successors
            )
    return planned, links
