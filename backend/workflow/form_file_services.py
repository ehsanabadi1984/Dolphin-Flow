                continue
            if change.action.value != "create":
                continue
            if change.desired_row == normalized_row:
                row = save_result.created_rows.get(change.row_reference)
                if row is not None:
                    return str(row.pk)
                return None

    return None


def _save_repeatable_group_files(
    *,