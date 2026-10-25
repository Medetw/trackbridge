from app.models import ParcelStatus

STATUS_LABELS_RU: dict[ParcelStatus, str] = {
    ParcelStatus.registered: "Зарегистрирована",
    ParcelStatus.received_at_china_wh: "Принята на складе в Китае",
    ParcelStatus.in_transit: "В пути в Казахстан",
    ParcelStatus.customs: "На таможне",
    ParcelStatus.ready_in_kz: "Готова к выдаче в Казахстане",
    ParcelStatus.delivered: "Выдана",
}


def status_label(status: ParcelStatus) -> str:
    return STATUS_LABELS_RU[status]


def status_change_text(tracking_code: str, client_name: str, new_status: ParcelStatus) -> str:
    return (
        f"Здравствуйте, {client_name}!\n"
        f"Статус посылки {tracking_code}: {status_label(new_status)}."
    )
