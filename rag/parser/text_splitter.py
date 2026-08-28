import re
import unicodedata

from langchain_text_splitters import RecursiveCharacterTextSplitter


def clean_cjk_spaces(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        keep_separator=False,
    )
    return splitter.split_text(text)
