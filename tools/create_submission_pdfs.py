"""Build the submission PDFs from the verified presentation renders and project evidence."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "final"
RENDERS = ROOT / "artifacts" / "presentation-render"

NAVY = colors.HexColor("#071a37")
BLUE = colors.HexColor("#0b6ff4")
CYAN = colors.HexColor("#dff2ff")
INK = colors.HexColor("#0b1f3a")
MUTED = colors.HexColor("#5f6f85")
LINE = colors.HexColor("#d7e0eb")
GREEN = colors.HexColor("#157f5b")
RED = colors.HexColor("#b42318")


def register_fonts() -> tuple[str, str]:
    regular = Path("C:/Windows/Fonts/arial.ttf")
    bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if not regular.exists() or not bold.exists():
        raise FileNotFoundError("Arial fonts are required to render Russian text")
    pdfmetrics.registerFont(TTFont("SafeSort", str(regular)))
    pdfmetrics.registerFont(TTFont("SafeSort-Bold", str(bold)))
    return "SafeSort", "SafeSort-Bold"


FONT, FONT_BOLD = register_fonts()


def draw_contained(c: canvas.Canvas, path: Path, x: float, y: float, width: float, height: float) -> None:
    with Image.open(path) as source:
        iw, ih = source.size
    scale = min(width / iw, height / ih)
    w, h = iw * scale, ih * scale
    c.drawImage(str(path), x + (width - w) / 2, y + (height - h) / 2, w, h, preserveAspectRatio=True, mask="auto")


def build_presentation_pdf() -> None:
    output = OUT / "presentation.pdf"
    c = canvas.Canvas(str(output), pagesize=landscape(A4), pageCompression=1)
    page_w, page_h = landscape(A4)
    for index in range(1, 10):
        slide = RENDERS / f"slide-{index:02d}.png"
        draw_contained(c, slide, 0, 0, page_w, page_h)
        c.showPage()
    c.save()


def report_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=styles["Title"], fontName=FONT_BOLD, fontSize=28, leading=34, textColor=INK, spaceAfter=10 * mm
        ),
        "h1": ParagraphStyle(
            "H1", parent=styles["Heading1"], fontName=FONT_BOLD, fontSize=22, leading=27, textColor=INK, spaceAfter=6 * mm
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=styles["Heading2"],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=19,
            textColor=NAVY,
            spaceBefore=4 * mm,
            spaceAfter=2.5 * mm,
        ),
        "body": ParagraphStyle(
            "Body", parent=styles["BodyText"], fontName=FONT, fontSize=10.5, leading=15, textColor=INK, spaceAfter=3.5 * mm
        ),
        "lead": ParagraphStyle(
            "Lead", parent=styles["BodyText"], fontName=FONT, fontSize=14, leading=20, textColor=NAVY, spaceAfter=6 * mm
        ),
        "small": ParagraphStyle("Small", parent=styles["BodyText"], fontName=FONT, fontSize=8.5, leading=12, textColor=MUTED),
        "callout": ParagraphStyle(
            "Callout", parent=styles["BodyText"], fontName=FONT_BOLD, fontSize=13, leading=18, textColor=NAVY, alignment=TA_CENTER
        ),
        "center": ParagraphStyle(
            "Center", parent=styles["BodyText"], fontName=FONT, fontSize=10, leading=14, textColor=MUTED, alignment=TA_CENTER
        ),
    }


def fit_image(path: Path, max_width: float, max_height: float) -> RLImage:
    with Image.open(path) as source:
        iw, ih = source.size
    scale = min(max_width / iw, max_height / ih)
    return RLImage(str(path), width=iw * scale, height=ih * scale)


def bullet(text: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"• {text}", styles["body"])


def callout(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(text, styles["callout"])]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CYAN),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#a9d8f7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ]
        )
    )
    return table


def page_footer(c: canvas.Canvas, doc: SimpleDocTemplate) -> None:
    c.saveState()
    c.setStrokeColor(LINE)
    c.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
    c.setFont(FONT, 8)
    c.setFillColor(MUTED)
    c.drawString(20 * mm, 9 * mm, "SafeSort · Задача 3 · цифровой прототип")
    c.drawRightString(190 * mm, 9 * mm, str(doc.page))
    c.restoreState()


def build_report_pdf() -> None:
    styles = report_styles()
    output = OUT / "report.pdf"
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="SafeSort — отчёт по решению задачи 3",
        author="SafeSort team",
    )
    story: list[object] = []

    story += [
        Spacer(1, 14 * mm),
        Paragraph("SafeSort", styles["title"]),
        Paragraph("Цифровой испытательный стенд роботизированной сортировочной ячейки", styles["lead"]),
        fit_image(ROOT / "artifacts/design-audit/04-supplied-box-route-b.png", 170 * mm, 94 * mm),
        Spacer(1, 7 * mm),
        callout("Измерили → направили → подтвердили", styles),
        Spacer(1, 6 * mm),
        Paragraph(
            "Рабочее локальное демо запускается через Docker. Неизвестный STL разбирается в браузере; "
            "автоматика конвейера отдельно проверяется в физической симуляции Webots.",
            styles["body"],
        ),
        PageBreak(),
    ]

    story += [
        Paragraph("1. Что решает SafeSort", styles["h1"]),
        Paragraph(
            "Задача требует обнаружить товар, определить его тип средствами компьютерного зрения и направить в нужную зону. "
            "В нашем цифровом прототипе тип — это маршрут B, C или D, заданный условиями по габаритам и форме.",
            styles["body"],
        ),
        Paragraph("Почему одной буквы недостаточно", styles["h2"]),
        Paragraph(
            "На конвейере решение должно стать действием: заслонки переключаются в нужный момент, "
            "товар пересекает выбранный выход, а датчик подтверждает результат. "
            "Если подтверждения нет, следующий выпуск блокируется.",
            styles["body"],
        ),
        callout("SafeSort проверяет не только решение, но и его исполнение.", styles),
        Spacer(1, 7 * mm),
        Paragraph("Границы проекта", styles["h2"]),
        bullet("Это цифровой прототип без физического оборудования.", styles),
        bullet(
            "Браузерный STL-анализ и Webots-сценарии связаны правилами и алгоритмами, но не являются одним автоматическим запуском.", styles
        ),
        bullet("Расчётная производительность требует проверки на реальном стенде.", styles),
        PageBreak(),
    ]

    data = [
        [Paragraph("Маршрут", styles["h2"]), Paragraph("Условие", styles["h2"]), Paragraph("Смысл", styles["h2"])],
        ["B", "габариты допустимы, K ≤ 0,8", "стандартный поток"],
        ["C", "хотя бы один размер не проходит строгую границу", "габаритная ветка"],
        ["D", "габариты допустимы, K > 0,8", "ветка близких к круглой форме товаров"],
    ]
    table = Table(data, colWidths=[25 * mm, 85 * mm, 60 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), CYAN),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    story += [
        Paragraph("2. Правила и инженерный вклад", styles["h1"]),
        Paragraph("Пороги B/C/D даны организаторами. Команда не выдаёт их за уникальность решения.", styles["lead"]),
        table,
        Spacer(1, 8 * mm),
        Paragraph("Что разработано", styles["h2"]),
        bullet("Пять карт глубины для измерения товара со всех сторон.", styles),
        bullet("Ориентированный габарит и оценка формы, устойчивые к повороту модели.", styles),
        bullet("Управление двумя заслонками по позиции товара на ленте.", styles),
        bullet("Подтверждение фактического выхода и безопасная остановка при отказе.", styles),
        PageBreak(),
    ]

    story += [
        Paragraph("3. Два контура проверки", styles["h1"]),
        Paragraph(
            "Браузер отвечает на вопрос «какой маршрут получает неизвестный STL?». "
            "Webots отвечает на вопрос «исполнит ли автоматика этот маршрут и подтвердит ли выход?». "
            "Эти доказательства дополняют друг друга, но не подменяют.",
            styles["lead"],
        ),
        fit_image(RENDERS / "slide-02.png", 170 * mm, 95 * mm),
        Spacer(1, 6 * mm),
        bullet("STL задаёт форму виртуального товара для проверки.", styles),
        bullet("Во время Webots-цикла контроллер получает только карты глубины, положение ленты и датчики автоматики.", styles),
        bullet("Имя STL и правильный класс контроллеру недоступны.", styles),
        PageBreak(),
    ]

    story += [
        Paragraph("4. Компьютерное зрение и геометрия", styles["h1"]),
        Paragraph(
            "Компьютерное зрение в SafeSort — восстановление геометрии по пяти виртуальным датчикам глубины. "
            "Для явно заданных правил B/C/D детерминированное измерение легче проверить и безопаснее исполнять, "
            "чем непрозрачный классификатор.",
            styles["body"],
        ),
        fit_image(ROOT / "artifacts/postcal-final3-gpu-b/rangefinder-front.png", 170 * mm, 82 * mm),
        Spacer(1, 5 * mm),
        Paragraph(
            "Из облака точек строится ориентированный габарит. Форма оценивается по нескольким поперечным сечениям; "
            "K равно отношению радиуса вписанной окружности к радиусу описанной.",
            styles["body"],
        ),
        callout("11 из 11 выданных STL совпали с независимой геометрической проверкой, включая повёрнутые модели.", styles),
        PageBreak(),
    ]

    webots_table = Table(
        [
            [
                fit_image(ROOT / "artifacts/design-audit/webots-final/b.png", 52 * mm, 42 * mm),
                fit_image(ROOT / "artifacts/design-audit/webots-final/c.png", 52 * mm, 42 * mm),
                fit_image(ROOT / "artifacts/design-audit/webots-final/d.png", 52 * mm, 42 * mm),
            ],
            [
                Paragraph("B: выход B", styles["center"]),
                Paragraph("C: выход C", styles["center"]),
                Paragraph("D: выход D", styles["center"]),
            ],
        ],
        colWidths=[56 * mm] * 3,
    )
    webots_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story += [
        Paragraph("5. Физическая симуляция маршрутов", styles["h1"]),
        Paragraph("Webots проверяет движение товара, положение двух заслонок и срабатывание нужного выходного датчика.", styles["lead"]),
        webots_table,
        Spacer(1, 8 * mm),
        bullet("B проходит обе развилки прямо.", styles),
        bullet("C уходит на первой развилке.", styles),
        bullet("D проходит первую развилку и уходит на второй.", styles),
        bullet("SUCCESS появляется только после события выбранного датчика выхода.", styles),
        PageBreak(),
    ]

    story += [
        Paragraph("6. Отказоустойчивость", styles["h1"]),
        fit_image(ROOT / "artifacts/design-audit/webots-final/fault.png", 170 * mm, 88 * mm),
        Spacer(1, 6 * mm),
        Paragraph(
            "В отказном сценарии датчик выхода отключён. Товар продолжает движение в симуляции, но подтверждения нет. "
            "Цикл заканчивается с FAULT, а следующий выпуск удерживается до явного сброса.",
            styles["lead"],
        ),
        callout("Нет сигнала выхода — нет успешного цикла.", styles),
        Spacer(1, 5 * mm),
        bullet(
            "Сообщения оператору написаны обычным языком: «не могу определить товар», "
            "«маршрут не создан», «подтверждение выхода не получено».",
            styles,
        ),
        bullet("При ошибке заслонки переходят в безопасное положение.", styles),
        PageBreak(),
    ]

    metrics = Table(
        [
            [
                Paragraph("11 / 11", styles["h1"]),
                Paragraph("10 564", styles["h1"]),
                Paragraph("0", styles["h1"]),
                Paragraph("5 143 / ч", styles["h1"]),
            ],
            [
                Paragraph("STL совпали с независимой проверкой", styles["small"]),
                Paragraph("численных маршрута", styles["small"]),
                Paragraph("небезопасных маршрутов в этих циклах", styles["small"]),
                Paragraph("расчётная оценка; нужна стендовая проверка", styles["small"]),
            ],
        ],
        colWidths=[42 * mm] * 4,
    )
    metrics.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("TEXTCOLOR", (0, 1), (-1, -1), MUTED),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 3 * mm),
            ]
        )
    )
    story += [
        Paragraph("7. Доказательства и область применимости", styles["h1"]),
        metrics,
        Spacer(1, 10 * mm),
        Paragraph("Физическая симуляция", styles["h2"]),
        Paragraph("Маршруты B/C/D и отказ датчика выхода подтверждены отдельными Webots-прогонами.", styles["body"]),
        Paragraph("Численные модели", styles["h2"]),
        Paragraph(
            "Точность геометрии, логика потока и расчётная производительность проверены отдельными наборами тестов. "
            "Числа не выдаются за испытание оборудования.",
            styles["body"],
        ),
        Paragraph("Воспроизводимость", styles["h2"]),
        Paragraph(
            "Каждый прогон связан с конфигурацией, журналом, seed и SHA-256. Финальная проверка выполняется в чистом клоне.", styles["body"]
        ),
        PageBreak(),
    ]

    story += [
        Paragraph("8. Запуск и проверка жюри", styles["h1"]),
        Paragraph("Приоритетный запуск", styles["h2"]),
        callout(".\\scripts\\start-demo.ps1", styles),
        Spacer(1, 6 * mm),
        bullet("Скрипт собирает Docker-образ, ждёт healthcheck и открывает http://localhost:4173/.", styles),
        bullet("Если доступна NVIDIA GPU, Docker получает её автоматически; без GPU используется CPU.", styles),
        bullet("STL до 50 МБ разбирается локально в браузере.", styles),
        bullet("В результате видны размеры, K, маршрут, причина решения, журнал событий и JSON-отчёт.", styles),
        Spacer(1, 7 * mm),
        fit_image(ROOT / "artifacts/design-audit/02-start-single-upload.png", 170 * mm, 74 * mm),
        PageBreak(),
    ]

    story += [
        Paragraph("9. Переход к реальному оборудованию", styles["h1"]),
        Paragraph("Что переносится", styles["h2"]),
        bullet("расположение и роль пяти датчиков глубины;", styles),
        bullet("логика измерения размеров и формы;", styles),
        bullet("планирование момента переключения заслонок;", styles),
        bullet("подтверждение выхода и безопасное состояние при отказе.", styles),
        Paragraph("Что ещё нужно проверить", styles["h2"]),
        Table(
            [
                [Paragraph("• конкретные камеры, приводы и промышленный контроллер;", styles["body"])],
                [Paragraph("• калибровку на реальном стенде;", styles["body"])],
                [Paragraph("• скорость, износ, вибрации, освещение и разнообразие физических товаров.", styles["body"])],
            ],
            colWidths=[170 * mm],
            style=[
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ],
        ),
        Spacer(1, 10 * mm),
        callout("SafeSort измеряет товар, выбирает маршрут и не считает цикл успешным, пока датчик не подтвердит выход.", styles),
        Spacer(1, 8 * mm),
        Paragraph(
            "Репозиторий содержит код, Docker-конфигурацию, тесты, Webots-сценарии, "
            "инструкции по запуску и комплект материалов для защиты.",
            styles["body"],
        ),
    ]

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_presentation_pdf()
    build_report_pdf()


if __name__ == "__main__":
    main()
