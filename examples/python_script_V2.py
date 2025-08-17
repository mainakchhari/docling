import argparse
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON_101
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Docling example: baseline programmatic text only (no OCR), no tables"
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

    # 1) Baseline: programmatic text only (no OCR), no table structure
    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = False
    opts.layout_options.model_spec = DOCLING_LAYOUT_HERON_101
    opts.images_scale = 1.0

    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = conv.convert(args.pdf).document
    out_file = args.out / f"{args.pdf.stem}.no_tables.md"
    out_file.write_text(doc.export_to_markdown())
    print(f"Wrote: {out_file}")

    # 2) If you need tables but header gets scrambled, you can switch:
    # opts.do_table_structure = True
    # opts.table_structure_options.mode = TableFormerMode.ACCURATE
    # opts.table_structure_options.do_cell_matching = False


if __name__ == "__main__":
    main()
