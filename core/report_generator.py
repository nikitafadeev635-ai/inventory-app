"""
Генератор PDF-отчётов по итогам нормализации.
Поддержка кириллицы через системный шрифт Arial.
Включает блок верификации, финансовой ответственности и помилований.

v2.1 — Финансовая разбивка + все ссылки из trouble_operations
"""
import os
import re
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, HRFlowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

from core.session import current_session


# ============================================================
#  РЕГИСТРАЦИЯ ШРИФТА С КИРИЛЛИЦЕЙ
# ============================================================
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

def _register_cyrillic_font():
    global _FONT_NAME, _FONT_BOLD

    candidates = []

    windir = os.environ.get('WINDIR', r'C:\Windows')
    fonts_dir = os.path.join(windir, 'Fonts')
    candidates.extend([
        (os.path.join(fonts_dir, 'arial.ttf'),
         os.path.join(fonts_dir, 'arialbd.ttf'),
         os.path.join(fonts_dir, 'ariali.ttf'),
         os.path.join(fonts_dir, 'arialbi.ttf')),
        (os.path.join(fonts_dir, 'ARIAL.TTF'),
         os.path.join(fonts_dir, 'ARIALBD.TTF'),
         os.path.join(fonts_dir, 'ARIALI.TTF'),
         os.path.join(fonts_dir, 'ARIALBI.TTF')),
        (os.path.join(fonts_dir, 'segoeui.ttf'),
         os.path.join(fonts_dir, 'segoeuib.ttf'),
         os.path.join(fonts_dir, 'segoeuii.ttf'),
         os.path.join(fonts_dir, 'segoeuiz.ttf')),
    ])

    candidates.extend([
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf'),
        ('/System/Library/Fonts/Helvetica.ttc', None, None, None),
    ])

    for paths in candidates:
        regular, bold, italic, bold_italic = paths
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont('CyrillicFont', regular))

                if bold and os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Bold', bold))
                else:
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Bold', regular))

                if italic and os.path.exists(italic):
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Italic', italic))
                else:
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Italic', regular))

                if bold_italic and os.path.exists(bold_italic):
                    pdfmetrics.registerFont(TTFont('CyrillicFont-BoldItalic', bold_italic))
                else:
                    pdfmetrics.registerFont(TTFont('CyrillicFont-BoldItalic', regular))

                registerFontFamily('CyrillicFont',
                                   normal='CyrillicFont',
                                   bold='CyrillicFont-Bold',
                                   italic='CyrillicFont-Italic',
                                   boldItalic='CyrillicFont-BoldItalic')

                _FONT_NAME = "CyrillicFont"
                _FONT_BOLD = "CyrillicFont-Bold"
                print(f"[Report] ✓ Шрифт с кириллицей зарегистрирован: "
                      f"{os.path.basename(regular)}")
                return
            except Exception as e:
                print(f"[Report] ⚠ Не удалось зарегистрировать {regular}: {e}")
                continue

    print("[Report] ⚠ Системный шрифт с кириллицей не найден, "
          "используется Helvetica (возможен mojibake)")


_register_cyrillic_font()


# ============================================================
#  ПАПКА ОТЧЁТОВ
# ============================================================
from core.paths import get_reports_dir
REPORTS_DIR = get_reports_dir()


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '-', name)
    name = re.sub(r'\s*-\s*', ' - ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 150:
        name = name[:150]
    return name


def _build_report_filename() -> str:
    if current_session.start_time:
        date_str = current_session.start_time.strftime("%d.%m.%Y")
    else:
        date_str = datetime.now().strftime("%d.%m.%Y")

    point = current_session.point_name or "Неизвестная точка"
    giver = current_session.giver or "Неизвестный сменщик"
    shift_type = current_session.shift_type or "Неизвестная смена"

    raw_name = f"{date_str} - {point} - {giver} - {shift_type}"
    safe_name = _sanitize_filename(raw_name)

    filename = f"{safe_name}.pdf"
    filepath = REPORTS_DIR / filename

    counter = 1
    while filepath.exists():
        filename = f"{safe_name} ({counter}).pdf"
        filepath = REPORTS_DIR / filename
        counter += 1

    return filename


def generate_normalization_report(discrepancies: list, result: dict,
                                   verification_result=None, trouble_result=None,
                                   financial_summary: dict = None) -> str:
    """
    Генерирует PDF-отчёт по нормализации с поддержкой кириллицы.

    Args:
        discrepancies: список DiscrepancyItem
        result: результат из NormalizationWorker
        verification_result: VerificationResult из верификатора (опционально)
        trouble_result: результат из TroubleDialog (опционально)
        financial_summary: данные о финансовой ответственности (опционально)

    Returns:
        Путь к созданному PDF файлу.
    """
    filename = _build_report_filename()
    filepath = REPORTS_DIR / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    # ============================================================
    #  СТИЛИ
    # ============================================================
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontName=_FONT_BOLD,
        fontSize=18,
        leading=22,
        spaceAfter=6,
        textColor=colors.HexColor('#2C87FD'),
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName=_FONT_NAME,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#64748b'),
        spaceAfter=4,
    )

    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#2C87FD'),
        spaceAfter=8,
        spaceBefore=8,
    )

    normal_style = ParagraphStyle(
        'NormalCyr',
        parent=styles['Normal'],
        fontName=_FONT_NAME,
        fontSize=10,
        leading=13,
    )

    success_style = ParagraphStyle(
        'Success',
        parent=normal_style,
        textColor=colors.HexColor('#27AE60'),
        fontName=_FONT_BOLD,
        fontSize=12,
    )

    warning_style = ParagraphStyle(
        'Warning',
        parent=normal_style,
        textColor=colors.HexColor('#F59E0B'),
        fontName=_FONT_BOLD,
        fontSize=11,
    )

    error_style = ParagraphStyle(
        'Error',
        parent=normal_style,
        textColor=colors.HexColor('#EF4444'),
        fontSize=9,
    )

    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName=_FONT_NAME,
        fontSize=8,
        textColor=colors.grey,
    )

    elements = []

    # ============================================================
    #  ШАПКА
    # ============================================================
    elements.append(Paragraph("Отчёт по нормализации товаров", title_style))
    elements.append(Spacer(1, 4))

    elements.append(Paragraph(
        f"Точка: <b>{current_session.point_name or '—'}</b> &nbsp;|&nbsp; "
        f"Дата: <b>{datetime.now().strftime('%d.%m.%Y %H:%M')}</b>",
        subtitle_style
    ))
    elements.append(Paragraph(
        f"Отдающий смену: <b>{current_session.giver or '—'}</b> &nbsp;|&nbsp; "
        f"Принимающий: <b>{current_session.receiver or '—'}</b>",
        subtitle_style
    ))
    elements.append(Paragraph(
        f"Смена: <b>{current_session.shift_label or '—'}</b> &nbsp;|&nbsp; "
        f"Тип: <b>{current_session.shift_type or '—'}</b>",
        subtitle_style
    ))
    elements.append(Paragraph(
        f"Длительность пересчёта: <b>{current_session.elapsed_str}</b>",
        subtitle_style
    ))

    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1,
                                color=colors.HexColor('#2C87FD')))
    elements.append(Spacer(1, 10))

    # ============================================================
    #  СВОДКА
    # ============================================================
    total_ops = result.get("success", 0) + result.get("failed", 0)
    disposals = [d for d in discrepancies if d.status == "less"]
    additions = [d for d in discrepancies if d.status == "more"]

    elements.append(Paragraph(
        f"Всего операций: <b>{total_ops}</b> &nbsp;|&nbsp; "
        f"Списано: <b>{len(disposals)}</b> &nbsp;|&nbsp; "
        f"Внесено: <b>{len(additions)}</b> &nbsp;|&nbsp; "
        f"Ошибок API: <b>{result.get('failed', 0)}</b>",
        header_style
    ))
    elements.append(Spacer(1, 8))

    # ============================================================
    #  ТАБЛИЦА РАСХОЖДЕНИЙ
    # ============================================================
    if discrepancies:
        elements.append(Paragraph("Детализация расхождений:", header_style))

        table_data = [["№", "Товар", "Было", "Стало", "Δ", "Операция", "Статус"]]

        for idx, item in enumerate(discrepancies, start=1):
            op_text = "СПИСАНИЕ" if item.status == "less" else "ВНЕСЕНИЕ"
            table_data.append([
                str(idx),
                item.title[:40],
                str(item.stock),
                str(item.actual),
                str(item.delta),
                op_text,
                "—",
            ])

        t = Table(table_data, colWidths=[20, 150, 35, 35, 30, 60, 145])

        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#161C23')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2C87FD')),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), _FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (4, -1), 'CENTER'),
            ('ALIGN', (5, 0), (5, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#0D1217'), colors.HexColor('#161C23')]),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.white),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]

        for i, item in enumerate(discrepancies, start=1):
            if item.status == "less":
                style_commands.append(
                    ('BACKGROUND', (5, i), (5, i), colors.HexColor('#FF3636')))
                style_commands.append(
                    ('TEXTCOLOR', (5, i), (5, i), colors.white))
            else:
                style_commands.append(
                    ('BACKGROUND', (5, i), (5, i), colors.HexColor('#27AE60')))
                style_commands.append(
                    ('TEXTCOLOR', (5, i), (5, i), colors.white))

        t.setStyle(TableStyle(style_commands))
        elements.append(t)
    else:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            "✓ Расхождений не обнаружено. Все товары сошлись с учётом.",
            success_style
        ))

    # ============================================================
    #  ИТОГИ ПО КАЖДОМУ ТИПУ
    # ============================================================
    if discrepancies:
        elements.append(Spacer(1, 14))
        elements.append(Paragraph("Итоги:", header_style))

        total_disposal_qty = sum(abs(d.delta) for d in disposals)
        total_addition_qty = sum(abs(d.delta) for d in additions)

        summary_lines = []
        if disposals:
            summary_lines.append(
                f"• <b>Списано:</b> {len(disposals)} позиций, "
                f"{total_disposal_qty} ед."
            )
        if additions:
            summary_lines.append(
                f"• <b>Внесено:</b> {len(additions)} позиций, "
                f"{total_addition_qty} ед."
            )

        for line in summary_lines:
            elements.append(Paragraph(line, normal_style))

    # ============================================================
    #  РЕЗУЛЬТАТЫ ВЕРИФИКАЦИИ В SMARTSHELL
    # ============================================================
    if verification_result is not None:
        elements.append(Spacer(1, 16))
        elements.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor('#64748b')))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("🔍 Верификация в SmartShell", header_style))

        if verification_result.all_ok:
            elements.append(Paragraph(
                f"✓ Все {verification_result.total} операций подтверждены в SmartShell. "
                f"Фактические остатки совпадают с ожидаемыми.",
                success_style
            ))
            elements.append(Paragraph(
                f"Раундов проверки: {verification_result.check_rounds}",
                normal_style
            ))
        else:
            elements.append(Paragraph(
                f"⚠ {verification_result.failed_count} из "
                f"{verification_result.total} операций не подтверждены "
                f"(после {verification_result.check_rounds} раундов проверки).",
                warning_style
            ))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(
                "Эти товары требуют ручной проверки в SmartShell:",
                normal_style
            ))
            elements.append(Spacer(1, 4))

            failed_table = [["Товар", "Операция", "Ожидалось", "Факт", "Ошибка"]]
            for op in verification_result.failed_operations:
                op_text = ("Списание" if op.operation_type == "DISPOSAL"
                           else "Внесение")
                failed_table.append([
                    op.product_title[:30],
                    f"{op_text} ({op.delta:+d})",
                    str(op.expected_stock),
                    str(op.actual_stock) if op.actual_stock is not None else "—",
                    (op.last_error or "Неизвестно")[:40],
                ])

            ft = Table(failed_table, colWidths=[140, 75, 60, 50, 150])
            ft.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#78350F')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), _FONT_NAME),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FEF3C7')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#78350F')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(ft)

    # ============================================================
    #  💰 ФИНАНСОВАЯ ОТВЕТСТВЕННОСТЬ АДМИНИСТРАТОРА
    # ============================================================
    if financial_summary and financial_summary.get("compensation_groups"):
        elements.append(Spacer(1, 14))
        elements.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor('#64748b')))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            "💰 Финансовая ответственность администратора",
            header_style
        ))
        elements.append(Paragraph(
            "В группах с пересортом (плюсы и минусы внутри одного бренда) "
            "учитывается только <b>чистая разница</b>. "
            "Пересортированные товары компенсируют друг друга.",
            normal_style
        ))
        elements.append(Spacer(1, 6))
        
        # Сводная таблица по брендам (в штуках)
        fin_table = [["Бренд", "Списано (шт)", "Внесено (шт)", "Чистая Δ", "К списанию"]]
        
        total_minus_qty = 0
        total_plus_qty = 0
        
        for g in financial_summary["compensation_groups"]:
            minus_qty = sum(
                abs(p.actual - p.stock) 
                for p in g.get("minus_products", []) 
                if p.actual is not None
            )
            plus_qty = sum(
                abs(p.actual - p.stock) 
                for p in g.get("plus_products", []) 
                if p.actual is not None
            )
            
            total_minus_qty += minus_qty
            total_plus_qty += plus_qty
            
            fin_table.append([
                g["group_name"],
                f"{minus_qty} шт",
                f"{plus_qty} шт",
                f"{g['net_delta']:+d}",
                f"{g['liability_value']:.2f} ₽",
            ])
        
        fin_table.append([
            "ИТОГО",
            f"{total_minus_qty} шт",
            f"{total_plus_qty} шт",
            f"{financial_summary['total_liability_items']:+d}",
            f"{financial_summary['total_liability_value']:.2f} ₽",
        ])
        
        ft = Table(fin_table, colWidths=[120, 90, 90, 80, 105])
        ft.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7C3AED')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -2), _FONT_NAME),
            ('FONTNAME', (0, -1), (-1, -1), _FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2),
             [colors.white, colors.HexColor('#F5F3FF')]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E9D5FF')),
            ('TEXTCOLOR', (0, 1), (-1, -2), colors.HexColor('#1F2937')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#581C87')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(ft)
        
        elements.append(Spacer(1, 10))
        
        # Детальная таблица по товарам
        all_delta_groups = financial_summary.get("all_groups_with_delta", [])
        
        if all_delta_groups:
            elements.append(Paragraph("Детализация по товарам с расхождениями:", header_style))
            elements.append(Spacer(1, 4))
            
            detail_table = [["Бренд", "Товар", "Было", "Стало", "Δ", "Тип"]]
            
            for g in all_delta_groups:
                brand_name = g["group_name"]
                items_in_group = []
                
                for p in g.get("minus_products", []):
                    if p.actual is not None and p.actual != p.stock:
                        items_in_group.append((p, "СПИСАНИЕ"))
                
                for p in g.get("plus_products", []):
                    if p.actual is not None and p.actual != p.stock:
                        items_in_group.append((p, "ВНЕСЕНИЕ"))
                
                items_in_group.sort(key=lambda x: (0 if x[1] == "СПИСАНИЕ" else 1, x[0].title))
                
                for product, op_type in items_in_group:
                    delta = product.actual - product.stock
                    detail_table.append([
                        brand_name,
                        product.title[:35],
                        str(product.stock),
                        str(product.actual),
                        f"{delta:+d}",
                        op_type,
                    ])
            
            if len(detail_table) > 1:
                dt = Table(detail_table, colWidths=[80, 180, 45, 45, 40, 95])
                dt_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E40AF')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                    ('FONTNAME', (0, 1), (-1, -1), _FONT_NAME),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('ALIGN', (2, 0), (4, -1), 'CENTER'),
                    ('ALIGN', (5, 0), (5, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                     [colors.white, colors.HexColor('#F0F9FF')]),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]
                
                for i, row_data in enumerate(detail_table[1:], start=1):
                    if row_data[5] == "СПИСАНИЕ":
                        dt_style.append(('BACKGROUND', (5, i), (5, i), colors.HexColor('#FEE2E2')))
                        dt_style.append(('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#991B1B')))
                    else:
                        dt_style.append(('BACKGROUND', (5, i), (5, i), colors.HexColor('#D1FAE5')))
                        dt_style.append(('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#065F46')))
                
                dt.setStyle(TableStyle(dt_style))
                elements.append(dt)
        
        net_val = financial_summary.get("net_total_disposal_value", financial_summary['total_liability_value'])
        net_items = financial_summary.get("net_total_disposal_items", financial_summary['total_liability_items'])
        
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            f"✓ Сумма к списанию с администратора (с учётом пересорта): "
            f"<b>{net_val:.2f} ₽</b> "
            f"({net_items} шт чистой недостачи)",
            ParagraphStyle('FinalLiability', parent=normal_style,
                          textColor=colors.HexColor('#059669'),
                          fontName=_FONT_BOLD, fontSize=12)
        ))

    elif discrepancies:
        if financial_summary is not None:
            net_value = financial_summary.get("net_total_disposal_value", 0.0)
            net_items = financial_summary.get("net_total_disposal_items", 0)
            
            elements.append(Spacer(1, 8))
            if net_value > 0:
                elements.append(Paragraph(
                    f"💰 Сумма к списанию с администратора (с учётом пересорта): "
                    f"<b>{net_value:.2f} ₽</b> ({net_items} шт чистой недостачи)",
                    ParagraphStyle('NetLiability', parent=normal_style,
                        fontName=_FONT_BOLD, fontSize=11,
                        textColor=colors.HexColor('#059669'))
                ))
            else:
                elements.append(Paragraph(
                    f"✅ Все расхождения внутри брендов полностью скомпенсированы (пересорт). "
                    f"Сумма к списанию с администратора: <b>0.00 ₽</b>",
                    ParagraphStyle('NetLiabilityZero', parent=normal_style,
                        fontName=_FONT_BOLD, fontSize=11,
                        textColor=colors.HexColor('#059669'))
                ))
        else:
            total_disposal_cost = sum(
                abs(d.delta) * d.cost for d in discrepancies if d.status == "less"
            )
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(
                f"💰 Сумма к списанию с администратора: "
                f"<b>{total_disposal_cost:.2f} ₽</b>",
                ParagraphStyle('SimpleLiability', parent=normal_style,
                              fontName=_FONT_BOLD, fontSize=11,
                              textColor=colors.HexColor('#1F2937'))
            ))

    # ============================================================
    #  💰 ФИНАНСОВАЯ РАЗБИВКА (v2.2 — синхронизация с trouble_dialog)
    # ============================================================
    if trouble_result:
        # === ЕДИНЫЙ ИСТОЧНИК: trouble_operations ===
        all_refs_combined = []
        
        trouble_ops = trouble_result.get("trouble_operations", []) or []
        for op in trouble_ops:
            ref = (op.get("reference") or "").strip()
            if ref:
                qty = op.get("quantity", 0)
                cost = op.get("cost", 0) or 0
                title = op.get("product_title") or "Товар"
                all_refs_combined.append({
                    "product_title": title,
                    "group_name": op.get("group_name") or title,
                    "product_id": op.get("product_id"),
                    "reference": ref,
                    "quantity": qty,
                    "value": cost * qty,
                    "reason": op.get("reason") or "",
                })
        
        # === Берём готовые значения из trouble_result ===
        total_minus = trouble_result.get('totalMinus', 0.0) or 0.0
        disputed = trouble_result.get('disputed', 0.0) or 0.0
        to_pay = trouble_result.get('toPay', 0.0) or 0.0
        
        # Fallback если новые поля отсутствуют
        if total_minus == 0.0:
            total_minus = trouble_result.get('cost', 0.0) or 0.0
        if disputed == 0.0:
            disputed = trouble_result.get('costDisTrouble', 0.0) or 0.0
        if to_pay == 0.0:
            to_pay = trouble_result.get('costTrouble', 0.0) or 0.0
        
        check_qty_actual = sum(r.get("quantity", 0) for r in all_refs_combined)
        
        elements.append(Spacer(1, 14))
        elements.append(HRFlowable(width="100%", thickness=1,
                                    color=colors.HexColor('#F59E0B')))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            "💰 Финансовая разбивка по причинам",
            ParagraphStyle('TroubleHeader', parent=header_style,
                          textColor=colors.HexColor('#F59E0B'),
                          fontSize=13)
        ))
        elements.append(Paragraph(
            "Общий минус делится на: спорные (уважительная причина + ссылка) "
            "и к немедленному возмещению.",
            normal_style
        ))
        elements.append(Spacer(1, 8))

        # === Главная таблица разбивки ===
        summary_table = [
            ["Показатель", "Сумма", "Примечание"],
            ["💰 Общий минус", f"{total_minus:.2f} ₽", "Все недостачи (DISPOSAL)"],
            ["🔍 Спорные", f"{disputed:.2f} ₽", f"{check_qty_actual} шт (уважительная + ссылка)"],
            ["💳 К возмещению", f"{to_pay:.2f} ₽", "Общий минус - Спорные"],
        ]

        st = Table(summary_table, colWidths=[200, 120, 160])
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F59E0B')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), _FONT_NAME),
            ('FONTNAME', (0, -1), (-1, -1), _FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#FFFBEB')]),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F3F4F6')),
            ('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor('#374151')),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#FEF3C7')),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.HexColor('#92400E')),
            ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#FEE2E2')),
            ('TEXTCOLOR', (0, 3), (-1, 3), colors.HexColor('#991B1B')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(st)

        # === Таблица товаров на ручной проверке ===
        if all_refs_combined:
            elements.append(Spacer(1, 12))
            elements.append(Paragraph(
                f"🔍 Товары со ссылками ({len(all_refs_combined)} позиций):",
                ParagraphStyle('RefHeader', parent=header_style,
                              textColor=colors.HexColor('#D97706'))
            ))

            ref_table = [["Товар", "Кол-во", "Сумма", "Причина", "Ссылка"]]

            for ref in all_refs_combined:
                ref_table.append([
                    (ref.get('product_title') or '—')[:25],
                    f"{ref.get('quantity', 0)} шт",
                    f"{ref.get('value', 0):.2f} ₽",
                    (ref.get('reason') or '—')[:20],
                    (ref.get('reference') or '—')[:35],
                ])

            total_ref_qty = sum(r.get('quantity', 0) for r in all_refs_combined)
            total_ref_value = sum(r.get('value', 0) for r in all_refs_combined)
            ref_table.append([
                "ИТОГО",
                f"{total_ref_qty} шт",
                f"{total_ref_value:.2f} ₽",
                "",
                "",
            ])

            rt = Table(ref_table, colWidths=[130, 50, 70, 110, 155])
            rt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D97706')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -2), _FONT_NAME),
                ('FONTNAME', (0, -1), (-1, -1), _FONT_BOLD),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 0), (2, -1), 'CENTER'),
                ('ALIGN', (3, 0), (4, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#334155')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -2),
                 [colors.white, colors.HexColor('#FFFBEB')]),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FEF3C7')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#78350F')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(rt)

        # === Итоговая сумма к возмещению ===
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(
            f"💳 <b>ИТОГО К ВОЗМЕЩЕНИЮ АДМИНИСТРАТОРОМ: "
            f"{to_pay:.2f} ₽</b>",
            ParagraphStyle('FinalTrouble', parent=normal_style,
                          textColor=colors.HexColor('#DC2626'),
                          fontName=_FONT_BOLD, fontSize=13)
        ))
        
        # Лог для отладки
        print(f"[Report] 💰 Финансовая разбивка PDF:")
        print(f"    Общий минус:     {total_minus:.2f}₽")
        print(f"    Спорные:         {disputed:.2f}₽ ({check_qty_actual} шт)")
        print(f"    К возмещению:    {to_pay:.2f}₽")

    # ============================================================
    #  ОШИБКИ API
    # ============================================================
    errors = result.get("errors", [])
    if errors:
        elements.append(Spacer(1, 14))
        elements.append(Paragraph(
            "⚠️ Ошибки при обработке:",
            ParagraphStyle('ErrorHeader', parent=header_style,
                          textColor=colors.HexColor('#FF3636'))
        ))
        for err in errors:
            elements.append(Paragraph(f"• {err}", error_style))

    # ============================================================
    #  ФУТЕР
    # ============================================================
    elements.append(Spacer(1, 24))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f"Сформировано автоматически · CyberMG Inventory · "
        f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        footer_style
    ))
    elements.append(Paragraph(
        f"Файл отчёта: {filename}",
        footer_style
    ))

    # ============================================================
    #  ГЕНЕРАЦИЯ
    # ============================================================
    doc.build(elements)
    print(f"[Report] ✓ PDF сохранён: {filepath}")
    return str(filepath)