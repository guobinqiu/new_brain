import zipfile


def validate_docx_file(filepath: str) -> None:
    try:
        with zipfile.ZipFile(filepath) as archive:
            if "[Content_Types].xml" not in archive.namelist() or not any(name.startswith("word/") for name in archive.namelist()):
                raise ValueError("Invalid docx file")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid docx file") from exc


def validate_xlsx_file(filepath: str) -> None:
    try:
        with zipfile.ZipFile(filepath) as archive:
            if "[Content_Types].xml" not in archive.namelist() or not any(name.startswith("xl/") for name in archive.namelist()):
                raise ValueError("Invalid xlsx file")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid xlsx file") from exc


def validate_pdf_file(filepath: str) -> None:
    import fitz

    try:
        doc = fitz.open(filepath)
    except Exception as exc:
        raise ValueError("Invalid pdf file") from exc
    finally:
        try:
            doc.close()
        except UnboundLocalError:
            pass


def validate_image_file(filepath: str) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(filepath) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Invalid image file") from exc
