from app.core.localization import datetime_label, enum_label
from app.core.config import BASE_DIR
from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["min"] = min
templates.env.globals["max"] = max
templates.env.globals["len"] = len
templates.env.globals["enumerate"] = enumerate
templates.env.filters["enum_label"] = enum_label
templates.env.filters["datetime_label"] = datetime_label
