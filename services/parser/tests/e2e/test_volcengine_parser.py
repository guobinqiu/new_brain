import yaml
import pytest

from services.parser.app.config import DEFAULT_CONFIG_FILE, load_parser_config
from services.parser.service import ParserService
from services.parser.common.schema import TextBlock


pytestmark = pytest.mark.e2e


def test_real_volcengine_pdf(tmp_path):
    # 单页文本 PDF，无第三方模型或本地解析服务依赖
    stream = b"BT /F1 18 Tf 72 720 Td (Volcano parser verification 7429) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path = tmp_path / "verification.pdf"
    path.write_bytes(pdf)
    raw = yaml.safe_load(DEFAULT_CONFIG_FILE.read_text())
    for name, backend in raw["parser"].items():
        backend["enable"] = name == "volcengine"
    config_path = tmp_path / "parser.yaml"
    config_path.write_text(yaml.safe_dump(raw))
    config = load_parser_config(config_path)
    service = ParserService(config)
    try:
        service.start()
        blocks = service.parse_file(str(path))
        text = " ".join(block.text for block in blocks if isinstance(block, TextBlock))
        assert "7429" in text
        assert "Volcano" in text
    finally:
        service.stop()
