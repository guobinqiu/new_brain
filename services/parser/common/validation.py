import zipfile


class InvalidDocumentError(ValueError):
    pass


def validate_docx_file(filepath: str) -> None:
    try:
        with zipfile.ZipFile(filepath) as archive:
            if "[Content_Types].xml" not in archive.namelist() or not any(name.startswith("word/") for name in archive.namelist()):
                raise InvalidDocumentError("Invalid docx file")
    except zipfile.BadZipFile as exc:
        raise InvalidDocumentError("Invalid docx file") from exc


def validate_xlsx_file(filepath: str) -> None:
    try:
        with zipfile.ZipFile(filepath) as archive:
            if "[Content_Types].xml" not in archive.namelist() or not any(name.startswith("xl/") for name in archive.namelist()):
                raise InvalidDocumentError("Invalid xlsx file")
    except zipfile.BadZipFile as exc:
        raise InvalidDocumentError("Invalid xlsx file") from exc


def validate_pptx_file(filepath: str) -> None:
    try:
        with zipfile.ZipFile(filepath) as archive:
            if "[Content_Types].xml" not in archive.namelist() or not any(name.startswith("ppt/") for name in archive.namelist()):
                raise InvalidDocumentError("Invalid pptx file")
    except zipfile.BadZipFile as exc:
        raise InvalidDocumentError("Invalid pptx file") from exc


def validate_pdf_file(filepath: str) -> None:
    import pymupdf

    try:
        with pymupdf.open(filepath):
            pass
    except Exception as exc:
        raise InvalidDocumentError("Invalid pdf file") from exc
