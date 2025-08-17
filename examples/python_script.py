import argparse
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON_101
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal Docling PDF -> Markdown example"
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file path")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("./.ungit"),
        help="Output directory (default: ./.ungit)",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    pipeline = PdfPipelineOptions()
    pipeline.do_ocr = False
    pipeline.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline.table_structure_options.do_cell_matching = False
    pipeline.layout_options.model_spec = DOCLING_LAYOUT_HERON_101

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
    )
    doc = converter.convert(args.pdf).document

    out_file = args.out / f"{args.pdf.stem}.md"
    out_file.write_text(doc.export_to_markdown())
    print(f"Wrote: {out_file}")


if __name__ == "__main__":
    main()
