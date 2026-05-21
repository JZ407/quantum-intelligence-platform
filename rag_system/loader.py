"""Document loaders for various file formats."""

import os
import zipfile
from xml.etree import ElementTree as ET
from pathlib import Path
from typing import List, Dict


def load_txt(path: str) -> str:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def load_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        return '\n'.join(texts)
    except Exception as e:
        raise RuntimeError(f"Failed to load PDF {path}: {e}")


def load_pptx(path: str) -> str:
    texts = []
    with zipfile.ZipFile(path, 'r') as z:
        slides = sorted([n for n in z.namelist()
                         if n.startswith('ppt/slides/slide') and n.endswith('.xml')])
        for slide_name in slides:
            content = z.read(slide_name)
            root = ET.fromstring(content)
            ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
            slide_texts = [t.text for t in root.iter(f'{{{ns}}}t') if t.text]
            if slide_texts:
                texts.append('\n'.join(slide_texts))
    return '\n\n'.join(texts)


def load_docx(path: str) -> str:
    texts = []
    with zipfile.ZipFile(path, 'r') as z:
        if 'word/document.xml' not in z.namelist():
            return ""
        content = z.read('word/document.xml')
        root = ET.fromstring(content)
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        for t in root.iter(f'{{{ns}}}t'):
            if t.text:
                texts.append(t.text)
    return '\n'.join(texts)


def load_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    loaders = {
        '.txt': load_txt, '.md': load_txt, '.csv': load_txt,
        '.json': load_txt, '.pdf': load_pdf, '.pptx': load_pptx,
        '.docx': load_docx,
    }
    if ext in loaders:
        return loaders[ext](path)
    raise ValueError(f"Unsupported file format: {ext} for {path}")


def load_directory(dir_path: str, recursive: bool = True) -> List[Dict]:
    supported = {'.txt', '.md', '.csv', '.json', '.pdf', '.pptx', '.docx'}
    docs = []
    root = Path(dir_path)
    pattern = '**/*' if recursive else '*'
    for p in root.glob(pattern):
        if p.is_file() and p.suffix.lower() in supported:
            try:
                content = load_file(str(p))
                docs.append({"source": str(p), "content": content})
            except Exception as e:
                print(f"[WARN] Skipped {p}: {e}")
    return docs
