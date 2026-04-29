from io import BytesIO
from urllib.parse import urljoin


def build_verify_url(base_url: str, report_number: str) -> str:
    return urljoin(str(base_url), f"/reports/verify/{report_number}")


def make_qr_data_uri(url: str) -> str | None:
    try:
        import qrcode
    except ImportError:
        return None

    buffer = BytesIO()
    image = qrcode.make(url)
    image.save(buffer, format="PNG")
    import base64

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
