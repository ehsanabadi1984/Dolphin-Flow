class OperatorFormSerializer:
    """Serialize workflow form state into the Operator Panel template contract."""

    @staticmethod
    def field(
        *,
        field,
        can_edit,
        permission_can_edit=None,
        value="",
        display_value="",
        choices=None,
        parent_code=None,
        device_types=None,
        device_models=None,
        is_immutable=None,
        is_imei_immutable=None,
    ):
        data = {
            "field": field,
            "can_edit": can_edit,
            "permission_can_edit": (
                can_edit
                if permission_can_edit is None
                else permission_can_edit
            ),
            "value": value,
            "display_value": display_value,
            "choices": choices or [],
            "parent_code": parent_code,
        }

        if device_types is not None:
            data["device_types"] = device_types

        if device_models is not None:
            data["device_models"] = device_models

        if is_immutable is not None:
            data["is_immutable"] = is_immutable

        if is_imei_immutable is not None:
            data["is_imei_immutable"] = is_imei_immutable

        return data
