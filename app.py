"""
ContabilIA — Generador de Reporte Fiscal 2025
Deploy: streamlit run app.py
Requiere: pip install streamlit fpdf2
"""

# Nombre de marca — cambiar cuando se defina el nombre del producto
BRAND_NAME = "ContabilIA"

import streamlit as st
from fpdf import FPDF
import datetime
import requests
import plotly.graph_objects as go

YEAR = datetime.date.today().year

# ============================================================
# CONSTANTES FISCALES 2025 (aproximadas — se actualizan trimestralmente)
# ============================================================

GAN_MNI           = 4_800_000
GAN_DED_ESP       = 14_400_000
GAN_CONYUGE       = 2_700_000
GAN_HIJO          = 1_350_000

GAN_ESCALA = [
    (0,            1_500_000,         0,  0.05),
    (1_500_000,    3_000_000,    75_000,  0.09),
    (3_000_000,    6_000_000,   210_000,  0.12),
    (6_000_000,   12_000_000,   570_000,  0.15),
   (12_000_000,   24_000_000, 1_470_000,  0.19),
   (24_000_000,   48_000_000, 3_750_000,  0.23),
   (48_000_000,   96_000_000, 9_270_000,  0.27),
   (96_000_000,  144_000_000,22_230_000,  0.31),
  (144_000_000,  float("inf"),37_110_000, 0.35),
]

MONO_SERVICIOS = [
    ("A",  8_840_000,  58_000),
    ("B", 13_100_000,  68_000),
    ("C", 18_400_000,  82_000),
    ("D", 25_700_000, 101_000),
    ("E", 32_700_000, 130_000),
    ("F", 41_500_000, 162_000),
    ("G", 51_700_000, 208_000),
    ("H", 64_700_000, 272_000),
]

BP_MNI               = 100_000_000
BP_TASA_LOCAL        = 0.005
BP_TASA_EXTERIOR     = 0.007
COSTO_CONTADOR_ANUAL = 1_200_000

# ============================================================
# LOGICA FISCAL
# ============================================================

def calcular_ganancias(base: float) -> float:
    if base <= 0:
        return 0.0
    for desde, hasta, fijo, pct in GAN_ESCALA:
        if base <= hasta:
            return fijo + (base - desde) * pct
    return 0.0


def get_categoria_mono(loc_anual: float):
    for cat, tope, cuota in MONO_SERVICIOS:
        if loc_anual <= tope:
            return cat, tope, cuota
    return None, None, None


def calcular_bp(saldo_usd: float, bienes_loc: float, tc: float):
    ext_ars   = saldo_usd * tc
    total     = ext_ars + bienes_loc
    if total <= BP_MNI:
        return 0.0, ext_ars
    exceso    = total - BP_MNI
    ratio_ext = ext_ars / total if total > 0 else 0
    bp        = exceso * (ratio_ext * BP_TASA_EXTERIOR + (1 - ratio_ext) * BP_TASA_LOCAL)
    return bp, ext_ars


def calcular_todo(ing_usd, tc, ing_local_mes, conyuge, hijos,
                  gastos_mes, saldo_ext, bienes_loc):

    ext_anual   = ing_usd * tc * 12
    loc_anual   = ing_local_mes * 12
    total_bruto = ext_anual + loc_anual

    ded_base  = GAN_MNI + GAN_DED_ESP
    ded_con   = GAN_CONYUGE if conyuge else 0
    ded_hij   = hijos * GAN_HIJO
    ded_total = ded_base + ded_con + ded_hij

    base_gan = max(0.0, total_bruto - ded_total)
    imp_gan  = calcular_ganancias(base_gan)

    cat, tope_cat, cuota_cat = get_categoria_mono(loc_anual)
    cuota_anual = (cuota_cat * 12) if cat else 0

    gastos_anual = gastos_mes * 12
    base_gan_ri  = max(0.0, total_bruto - ded_total - gastos_anual)
    imp_gan_ri   = calcular_ganancias(base_gan_ri)

    bp, ext_ars = calcular_bp(saldo_ext, bienes_loc, tc)

    total_mono = imp_gan + cuota_anual + bp
    total_ri   = imp_gan_ri + COSTO_CONTADOR_ANUAL + bp

    neto         = total_bruto - total_mono
    takehome_pct = (neto / total_bruto * 100) if total_bruto > 0 else 0

    # Margen antes de saltar de categoría (solo ingresos locales)
    cat_idx = next((i for i, (c, _, _) in enumerate(MONO_SERVICIOS) if c == cat), None)
    if cat_idx is not None and cat_idx + 1 < len(MONO_SERVICIOS):
        _, tope_sig, cuota_sig = MONO_SERVICIOS[cat_idx + 1]
        margen_cat = tope_sig - loc_anual
        cat_sig = MONO_SERVICIOS[cat_idx + 1][0]
        pct_cat = loc_anual / tope_cat if tope_cat else 0
    else:
        margen_cat, cat_sig, cuota_sig, pct_cat = 0, None, None, 1.0

    return dict(
        ext_anual=ext_anual, loc_anual=loc_anual, total_bruto=total_bruto,
        ded_base=ded_base, ded_con=ded_con, ded_hij=ded_hij, ded_total=ded_total,
        base_gan=base_gan, imp_gan=imp_gan,
        cat=cat, tope_cat=tope_cat, cuota_cat=cuota_cat, cuota_anual=cuota_anual,
        bp=bp, ext_ars=ext_ars,
        total_mono=total_mono, total_ri=total_ri,
        imp_gan_ri=imp_gan_ri, gastos_anual=gastos_anual,
        neto=neto, takehome_pct=takehome_pct,
        margen_cat=margen_cat, cat_sig=cat_sig, cuota_sig=cuota_sig, pct_cat=pct_cat,
    )

# ============================================================
# HELPER DE FORMATO
# ============================================================

def ars(n: float) -> str:
    return "$ " + f"{int(round(n)):,}".replace(",", ".")

def ars_m(n: float) -> str:
    """Formato abreviado en millones para métricas de header."""
    m = n / 1_000_000
    return f"$ {m:.1f}M"

def usd_fmt(n: float) -> str:
    """Formato compacto USD para widgets de métrica — evita truncado en 4 columnas."""
    if n >= 1_000:
        return f"USD {n/1_000:.1f}k"
    return f"USD {int(round(n))}"

# ============================================================
# TIPO DE CAMBIO BANCO NACION (automatico)
# ============================================================

@st.cache_data(ttl=3600)
def obtener_tc_bna():
    """
    Devuelve (venta, fecha_str, es_fallback).
    Retrocede hasta 7 dias para cubrir fines de semana y feriados.
    """
    from datetime import date, timedelta
    import re

    for dias_atras in range(7):
        fecha = date.today() - timedelta(days=dias_atras)
        fecha_str = fecha.strftime("%d/%m/%Y")
        try:
            url = (
                "https://www.bna.com.ar/Cotizador/HistoricasMoneda"
                f"?id=2&desde={fecha_str}&hasta={fecha_str}"
            )
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and "Dolar" in resp.text:
                matches = re.findall(r"<td[^>]*>\s*([\d,\.]+)\s*</td>", resp.text)
                numeros = [m.replace(",", ".") for m in matches if re.match(r"^\d{3,}", m.replace(",", ""))]
                if len(numeros) >= 2:
                    venta = int(round(float(numeros[1])))
                    return venta, fecha.strftime("%d/%m/%Y"), False
        except Exception:
            continue

    # Fallback: dolarapi.com (fuente alternativa con datos de BNA)
    try:
        resp = requests.get("https://dolarapi.com/v1/dolares/oficial", timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            venta = int(round(data["venta"]))
            fecha_raw = data.get("fechaActualizacion", "")
            if len(fecha_raw) >= 10:
                fecha_display = fecha_raw[8:10] + "/" + fecha_raw[5:7] + "/" + fecha_raw[:4]
            else:
                fecha_display = "N/D"
            return venta, fecha_display, False
    except Exception:
        pass

    return 1200, None, True  # True = fallback hardcodeado

# ============================================================
# GENERADOR DE PDF
# ============================================================

class ReportePDF(FPDF):
    BRAND = BRAND_NAME

    def header(self):
        y0 = self.get_y()

        # Logo mark: cuadrado azul + "C" blanca
        self.set_fill_color(37, 99, 235)
        self.rect(self.l_margin, y0, 5.5, 5.5, style="F")
        self.set_xy(self.l_margin, y0)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(255, 255, 255)
        self.cell(5.5, 5.5, "C", align="C")

        # "Contabil" en navy, "IA" en azul
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(15, 23, 42)
        self.cell(21, 5.5, "Contabil", align="L")
        self.set_text_color(37, 99, 235)
        self.cell(8, 5.5, "IA", align="L")

        # Fecha alineada a la derecha (se superpone hacia la derecha desde x=20)
        self.set_xy(self.l_margin, y0)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(148, 163, 184)
        self.cell(170, 5.5, f"Generado: {datetime.date.today().strftime('%d/%m/%Y')}", align="R")

        self.set_y(y0 + 7)
        self.set_draw_color(226, 232, 240)
        self.line(20, self.get_y(), 190, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-18)
        self.set_font("Helvetica", "", 6.5)
        self.set_text_color(148, 163, 184)
        self.multi_cell(
            0, 4,
            f"Valores estimados con parámetros fiscales aproximados {YEAR} (se actualizan trimestralmente). "
            "No constituye asesoramiento contable, impositivo ni legal. Consultá con un contador habilitado. "
            f"Página {self.page_no()} | {self.BRAND}",
            align="C",
        )


def _section(pdf: ReportePDF, titulo: str):
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 7, titulo, ln=True)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(3)


def _row(pdf: ReportePDF, label: str, valor: str, bold_val: bool = False, even: bool = False):
    if even:
        pdf.set_fill_color(249, 250, 251)
        pdf.rect(20, pdf.get_y(), 170, 7, "F")
    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(120, 7, label)
    pdf.set_font("Helvetica", "B" if bold_val else "", 9.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(40, 7, valor, align="R", ln=True)


def generar_pdf(inp: dict, r: dict) -> bytes:
    pdf = ReportePDF()
    pdf.set_margins(20, 22, 20)
    pdf.add_page()

    # ----- TITULO -----
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, f"Reporte de Proyección Fiscal {YEAR}", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 7, "Profesional independiente / Freelancer cobrador del exterior", ln=True)
    pdf.ln(4)

    # ----- BANNER RESUMEN -----
    y0 = pdf.get_y()
    pdf.set_fill_color(239, 246, 255)
    pdf.set_draw_color(191, 219, 254)
    pdf.rect(20, y0, 170, 34, "FD")
    pdf.set_xy(24, y0 + 3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 6, "Resumen ejecutivo", ln=True)
    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(37, 99, 235)
    cw = 56
    pdf.cell(cw, 6, f"Bruto anual: {ars(r['total_bruto'])}")
    pdf.cell(cw, 6, f"Carga fiscal: {ars(r['total_mono'])}")
    pdf.cell(cw, 6, f"Take-home: {r['takehome_pct']:.1f}%", ln=True)
    pdf.set_x(24)
    neto_mes_pdf = r["neto"] / 12
    neto_usd_pdf = neto_mes_pdf / inp["tc"] if inp["tc"] > 0 else 0
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(85, 6, f"Neto mensual ARS: {ars(neto_mes_pdf)}")
    pdf.cell(85, 6, f"Neto mensual USD: USD {neto_usd_pdf:,.0f}", ln=True)
    pdf.ln(12)

    # ----- SECCION 1: DATOS -----
    _section(pdf, "1. Datos ingresados")
    datos_filas = [
        ("Ingresos del exterior", f"USD {inp['ing_usd']:,.0f}/mes"),
        ("Tipo de cambio utilizado", f"ARS {inp['tc']:,.0f} por USD"),
        ("Ingresos en Argentina", ars(inp["ing_local_mes"]) + "/mes"),
        ("Estado civil", "Con cónyuge" if inp["conyuge"] else "Soltero/a"),
        ("Hijos a cargo", str(inp["hijos"])),
        ("Gastos profesionales deducibles", ars(inp["gastos_mes"]) + "/mes"),
        ("Saldo cuentas del exterior al 31/12", f"USD {inp['saldo_ext']:,.0f}"),
        ("Otros bienes en Argentina", ars(inp["bienes_loc"])),
    ]
    for i, (l, v) in enumerate(datos_filas):
        _row(pdf, l, v, even=(i % 2 == 0))
    pdf.ln(5)

    # ----- SECCION 2: GANANCIAS -----
    _section(pdf, "2. Impuesto a las Ganancias (4ta Categoría)")
    gan_filas = [
        ("Ingreso bruto anual en ARS", ars(r["total_bruto"]), False),
        ("  Min. no imponible + ded. especial 4ta", f"({ars(r['ded_base'])})", False),
    ]
    if r["ded_con"] > 0:
        gan_filas.append(("  Deducción cónyuge", f"({ars(r['ded_con'])})", False))
    if r["ded_hij"] > 0:
        gan_filas.append((f"  Deducción hijos ({inp['hijos']})", f"({ars(r['ded_hij'])})", False))
    gan_filas += [
        ("Base imponible Ganancias", ars(r["base_gan"]), False),
        ("Impuesto determinado", ars(r["imp_gan"]), True),
    ]
    for i, (l, v, bold) in enumerate(gan_filas):
        if bold:
            pdf.set_fill_color(254, 243, 199)
            pdf.rect(20, pdf.get_y(), 170, 8, "F")
            pdf.set_x(24)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(92, 40, 0)
            pdf.cell(120, 8, l)
            pdf.cell(40, 8, v, align="R", ln=True)
        else:
            _row(pdf, l, v, even=(i % 2 == 0))
    pdf.ln(5)

    # ----- SECCION 3: MONOTRIBUTO -----
    _section(pdf, "3. Régimen de Monotributo")
    if r["cat"]:
        pdf.set_fill_color(240, 253, 244)
        pdf.set_draw_color(134, 239, 172)
        pdf.rect(20, pdf.get_y(), 170, 8, "FD")
        pdf.set_x(24)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(20, 83, 45)
        pdf.cell(0, 8, "Factura E (exterior) NO computa para el tope de categoría", ln=True)
        mono_filas = [
            ("Ingresos locales anuales (base para categoría)", ars(r["loc_anual"])),
            ("Categoría asignada (servicios)", f"Categoría {r['cat']}"),
            ("Cuota mensual (impuesto + obra social + jubilación)", ars(r["cuota_cat"])),
            ("Costo anual Monotributo", ars(r["cuota_anual"])),
        ]
        for i, (l, v) in enumerate(mono_filas):
            _row(pdf, l, v, even=(i % 2 == 0))
    else:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(185, 28, 28)
        pdf.cell(0, 7, "ALERTA: ingresos locales superan tope Categoría H. Pase a RI obligatorio.", ln=True)
    pdf.ln(5)

    # ----- SECCION 4: BIENES PERSONALES -----
    _section(pdf, "4. Bienes Personales")
    bp_filas = [
        ("Activos en el exterior (en ARS al TC utilizado)", ars(r["ext_ars"])),
        ("Otros bienes en Argentina", ars(inp["bienes_loc"])),
        (f"Mínimo no imponible BP (aprox. {YEAR})", ars(BP_MNI)),
        ("Impuesto estimado Bienes Personales", ars(r["bp"])),
    ]
    for i, (l, v) in enumerate(bp_filas):
        _row(pdf, l, v, even=(i % 2 == 0))
    pdf.ln(5)

    # ----- CAJA RESUMEN PAGINA 1 -----
    y_s = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(20, y_s, 170, 38, "FD")
    pdf.set_xy(24, y_s + 4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, "Resumen de carga fiscal", ln=True)
    for l, v in [
        ("Impuesto a las Ganancias", ars(r["imp_gan"])),
        ("Cuota Monotributo anual",  ars(r["cuota_anual"])),
        ("Bienes Personales",        ars(r["bp"])),
    ]:
        pdf.set_x(24)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(120, 6, l)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(40, 6, v, align="R", ln=True)
    pdf.set_x(24)
    pdf.set_draw_color(203, 213, 225)
    pdf.line(24, pdf.get_y(), 186, pdf.get_y())
    pdf.set_x(24)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(92, 40, 0)
    pdf.cell(120, 8, "TOTAL / AÑO")
    pdf.cell(40, 8, ars(r["total_mono"]), align="R", ln=True)

    # ============================================================
    # PAGINA 2
    # ============================================================
    pdf.add_page()

    # ----- SECCION 5: COMPARATIVA -----
    _section(pdf, "5. Comparativa: Monotributo vs. Responsable Inscripto")

    cw1, cw2, cw3 = 82, 44, 44
    pdf.set_fill_color(241, 245, 249)
    pdf.set_x(20)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(cw1, 8, "Concepto", fill=True)
    pdf.cell(cw2, 8, "Monotributo", fill=True, align="C")
    pdf.cell(cw3, 8, "Resp. Inscripto", fill=True, align="C", ln=True)

    cmp_filas = [
        ("Impuesto a las Ganancias",    ars(r["imp_gan"]),       ars(r["imp_gan_ri"])),
        ("Cuota / Honorarios contador", ars(r["cuota_anual"]),   ars(COSTO_CONTADOR_ANUAL)),
        ("Bienes Personales",           ars(r["bp"]),            ars(r["bp"])),
        ("IVA sobre Factura E",         "No aplica",             "No aplica"),
        ("Gastos deducibles Ganancias", "No",                    ars(r["gastos_anual"]) + "/año"),
    ]
    for i, (l, vm, vr) in enumerate(cmp_filas):
        fc = (249, 250, 251) if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*fc)
        pdf.set_x(20)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(cw1, 7, l, fill=True)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(cw2, 7, vm, fill=True, align="C")
        pdf.cell(cw3, 7, vr, fill=True, align="C", ln=True)

    mono_gana = r["total_mono"] <= r["total_ri"]
    pdf.set_x(20)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 252, 231) if mono_gana else pdf.set_fill_color(254, 243, 199)
    pdf.set_text_color(20, 83, 45)   if mono_gana else pdf.set_text_color(92, 40, 0)
    pdf.cell(cw1, 9, "TOTAL / AÑO", fill=True)
    pdf.cell(cw2, 9, ars(r["total_mono"]), fill=True, align="C")
    pdf.set_fill_color(254, 243, 199) if mono_gana else pdf.set_fill_color(220, 252, 231)
    pdf.set_text_color(92, 40, 0)    if mono_gana else pdf.set_text_color(20, 83, 45)
    pdf.cell(cw3, 9, ars(r["total_ri"]), fill=True, align="C", ln=True)
    pdf.ln(6)

    # ----- SECCION 6: RECOMENDACION -----
    _section(pdf, "6. Recomendación")

    if not r["cat"]:
        rc, bc = (254, 242, 242), (252, 165, 165)
        tc_col, bc_col = (153, 27, 27), (185, 28, 28)
        titulo_rec = "Pase a Responsable Inscripto obligatorio"
        cuerpo_rec = (
            "Tus ingresos locales superan el tope máximo de Monotributo (Categoría H). "
            "El pase a RI es obligatorio según la normativa vigente. Consultá con tu contador."
        )
    elif mono_gana:
        rc, bc = (240, 253, 244), (134, 239, 172)
        tc_col, bc_col = (20, 83, 45), (22, 101, 52)
        ahorro = ars(r["total_ri"] - r["total_mono"])
        titulo_rec = f"Mantener Monotributo Categoría {r['cat']}"
        cuerpo_rec = (
            f"Con los datos ingresados, el Monotributo es más conveniente. "
            f"Ahorro anual vs RI: {ahorro}. "
            f"Tus ingresos del exterior (Factura E) no computan para el tope, "
            f"lo que te permite mantenerte en una categoría baja independientemente de lo que facturés en USD."
        )
    else:
        rc, bc = (255, 251, 235), (253, 230, 138)
        tc_col, bc_col = (92, 45, 0), (78, 42, 0)
        ahorro = ars(r["total_mono"] - r["total_ri"])
        titulo_rec = "Evaluar Responsable Inscripto"
        cuerpo_rec = (
            f"Con tus gastos profesionales ({ars(r['gastos_anual'])}/año), el RI podría ser conveniente. "
            f"Ahorro estimado: {ahorro}/año. "
            f"Considerá que el RI requiere contador permanente (~{ars(COSTO_CONTADOR_ANUAL)}/año) "
            f"y declaraciones mensuales de IVA y CM."
        )

    y_rec = pdf.get_y()
    pdf.set_fill_color(*rc)
    pdf.set_draw_color(*bc)
    pdf.rect(20, y_rec, 170, 36, "FD")
    pdf.set_xy(24, y_rec + 4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*tc_col)
    pdf.cell(0, 6, titulo_rec, ln=True)
    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*bc_col)
    pdf.multi_cell(162, 5, cuerpo_rec)
    pdf.ln(8)

    # ----- SECCION 7: TAKE-HOME -----
    _section(pdf, "7. Ingreso neto estimado")
    th_filas = [
        ("Ingreso bruto anual (ARS)",            ars(r["total_bruto"]),               False),
        ("Carga fiscal total estimada",          f"({ars(r['total_mono'])})",          False),
        ("Ingreso neto anual estimado",          ars(r["neto"]),                       True),
        ("Ingreso neto mensual estimado",        ars(r["neto"] / 12),                  True),
        ("Take-home rate efectivo",              f"{r['takehome_pct']:.1f}%",          True),
        ("Ingreso neto mensual en USD (aprox.)", f"USD {r['neto']/12/inp['tc']:,.0f}", True),
    ]
    for i, (l, v, bold) in enumerate(th_filas):
        if i >= 2 and i % 2 == 0:
            pdf.set_fill_color(249, 250, 251)
            pdf.rect(20, pdf.get_y(), 170, 7, "F")
        pdf.set_x(24)
        pdf.set_font("Helvetica", "B" if bold else "", 9.5)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(120, 7, l)
        pdf.cell(40, 7, v, align="R", ln=True)

    # ============================================================
    # PAGINA 3: PROXIMOS PASOS + NOTA PARA CONTADOR + CALENDARIO
    # ============================================================
    pdf.add_page()

    # ----- SECCION 8: PROXIMOS PASOS -----
    _section(pdf, "8. Próximos pasos recomendados")

    pasos = [
        ("Inscripción AFIP",
         "Si todavía no tenés CUIT activo con actividad de servicios al exterior, registrate en AFIP "
         "como Monotributista (o RI si corresponde) antes de cobrar el próximo mes."),
        ("Cuenta para cobros del exterior",
         "Usá Payoneer, Wise o una cuenta bancaria en el exterior para recibir los pagos. "
         "Convertí los fondos al TC oficial (BNA) para la liquidación impositiva."),
        ("Documentación de ingresos",
         "Guardá todos los comprobantes de cobro del exterior: contratos, recibos, extractos. "
         "Son necesarios ante una eventual fiscalización de AFIP."),
        ("Fecha de recategorización",
         "Si sos Monotributista, recategorizate en enero y julio de cada año comparando "
         "tus ingresos locales acumulados (no los del exterior)."),
        ("Declaración jurada anual Ganancias",
         "La DJ anual vence en junio del año siguiente. Con este reporte ya tenés los números "
         "base para presentarla. Compartila con tu contador con anticipación."),
        ("Bienes Personales",
         "Si tus activos totales superan el mínimo no imponible, la DJ de BP vence en junio "
         "junto con Ganancias. El saldo en cuentas del exterior al 31/12 es el dato clave."),
    ]

    for i, (titulo_paso, cuerpo_paso) in enumerate(pasos):
        y_p = pdf.get_y()
        fc = (249, 250, 251) if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*fc)
        pdf.set_x(20)
        # Numero de paso en circulo
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(8, 8, str(i + 1) + ".", fill=False)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 8, titulo_paso, ln=True)
        pdf.set_x(28)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(71, 85, 105)
        pdf.multi_cell(158, 5, cuerpo_paso)
        pdf.ln(2)

    pdf.ln(4)

    # ----- SECCION 9: NOTA PARA TU CONTADOR -----
    _section(pdf, "9. Nota para tu contador")

    y_nc = pdf.get_y()
    pdf.set_fill_color(239, 246, 255)
    pdf.set_draw_color(191, 219, 254)
    pdf.rect(20, y_nc, 170, 8, "FD")
    pdf.set_xy(24, y_nc + 1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 6,
        "Este bloque resume los datos clave para tu primera reunión con el contador.", ln=True)
    pdf.ln(2)

    regimen_actual = f"Monotributo Categoría {r['cat']}" if r["cat"] else "Responsable Inscripto (obligatorio)"
    nota_filas = [
        ("Actividad",                   "Servicios al exterior (Factura E) + locales"),
        ("Ingresos exterior",           f"USD {inp['ing_usd']:,.0f}/mes (ARS {ars(r['ext_anual'])}/año)"),
        ("Ingresos locales",            f"{ars(inp['ing_local_mes'])}/mes (ARS {ars(r['loc_anual'])}/año)"),
        ("Régimen sugerido",            regimen_actual),
        ("Carga fiscal estimada",       f"{ars(r['total_mono'])}/año ({r['takehome_pct']:.1f}% take-home)"),
        ("Activos exterior al 31/12",   f"USD {inp['saldo_ext']:,.0f}"),
        ("Otros bienes locales",        ars(inp["bienes_loc"])),
        ("Estado civil / hijos",        f"{'Con cónyuge' if inp['conyuge'] else 'Sin cónyuge'} / {inp['hijos']} hijo(s)"),
    ]
    for i, (l, v) in enumerate(nota_filas):
        _row(pdf, l, v, even=(i % 2 == 0))

    pdf.ln(5)

    # ----- SECCION 10: FECHAS CLAVE -----
    _section(pdf, "10. Fechas clave del calendario fiscal")

    cal_filas = [
        ("Pago mensual Monotributo",
         "Días 7 al 11 de cada mes según terminación de CUIT"),
        ("Recategorización Monotributo",
         "Enero y julio - basada en ingresos locales de los últimos 12 meses"),
        ("Anticipos Ganancias (5 cuotas)",
         "Agosto, septiembre, octubre, noviembre (año en curso) y febrero (año siguiente)"),
        ("DJ Ganancias anual (Personas Humanas)",
         "Junio del año siguiente al período fiscal"),
        ("DJ Bienes Personales",
         "Junio del año siguiente - mismo vencimiento que Ganancias"),
        ("Actualización de valores MNI y escalas",
         "Trimestral (enero, abril, julio, octubre) - los valores de este reporte son aproximados"),
    ]
    for i, (evento, fecha) in enumerate(cal_filas):
        fc = (249, 250, 251) if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*fc)
        pdf.set_x(20)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(85, 7, evento, fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(85, 7, fecha, fill=True, ln=True)

    pdf.ln(8)

    # ----- BLOQUE DE SERVICIO MENSUAL -----
    y_srv = pdf.get_y()
    # Si no entra en la pagina, saltar a nueva
    if y_srv > 230:
        pdf.add_page()
        y_srv = pdf.get_y()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(20, y_srv, 170, 6, "F")
    pdf.set_xy(24, y_srv + 1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 4, "Servicio de contabilidad para freelancers que cobran del exterior", ln=True)

    y_body = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(20, y_body, 170, 52, "FD")

    pdf.set_xy(24, y_body + 4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, "¿No tenés contador? Nosotros nos encargamos.", ln=True)

    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(71, 85, 105)
    pdf.multi_cell(
        162, 5,
        "Este reporte te da el panorama. Pero liquidar correctamente, presentar las declaraciones "
        "y no perder vencimientos requiere seguimiento mensual. Eso es lo que ofrecemos:",
    )
    pdf.ln(3)

    servicios = [
        "Liquidación y pago mensual del Monotributo",
        "Seguimiento de ingresos del exterior y recategorización automática",
        "Declaración Jurada anual de Ganancias y Bienes Personales",
        "Alertas de vencimientos y cambios normativos",
        "Consultas ilimitadas por WhatsApp o email",
    ]
    for srv in servicios:
        pdf.set_x(26)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(5, 5, "-")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 5, srv, ln=True)

    pdf.ln(3)
    pdf.set_x(24)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(0, 5, "Contacto: hola@contabilia.ar", ln=True)

    return bytes(pdf.output())

# ============================================================
# AUTENTICACION (codigos en .streamlit/secrets.toml)
# ============================================================

def codigo_valido(pwd: str) -> bool:
    try:
        lista = st.secrets["acceso"]["codigos"]
        return pwd.strip().upper() in [c.upper() for c in lista]
    except Exception:
        return pwd.strip().upper() == "DEMO2025"

# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(
    page_title=f"{BRAND_NAME} — Reporte Fiscal",
    page_icon="📄",
    layout="wide",
)

st.title(BRAND_NAME)
st.caption(f"Proyección fiscal {datetime.date.today().year} para profesionales que cobran del exterior · Ganancias · Monotributo · Bienes Personales")
st.divider()

col_form, col_res = st.columns([1, 1], gap="large")

with col_form:
    st.subheader("Tus datos")

    ing_usd = st.number_input(
        "Ingresos del exterior (USD/mes)",
        min_value=0,
        value=2000,
        step=100,
        help="Total mensual que cobrás de clientes o plataformas del exterior (Upwork, Fiverr, clientes directos, etc.).",
    )
    if ing_usd == 0:
        st.warning("Ingresá tus ingresos del exterior para calcular tu situación fiscal.")

    _tc_default, _tc_fecha, _tc_es_fallback = obtener_tc_bna()
    tc = st.number_input(
        "Tipo de cambio (ARS por USD)",
        min_value=1,
        value=_tc_default,
        step=50,
        help="Cotización vendedor Banco Nación. Podés modificarlo si usás otro tipo de cambio.",
    )
    if _tc_es_fallback:
        st.warning("No se pudo obtener el TC de Banco Nación. Se usa $1.200 como estimación — actualizalo manualmente.")
    elif _tc_fecha:
        st.caption(f"TC Banco Nación (venta) · última cotización disponible: {_tc_fecha}")

    ing_local_mes = st.number_input(
        "Ingresos en Argentina (ARS/mes, si tenés)",
        min_value=0,
        value=0,
        step=10_000,
        help="Facturación a clientes argentinos. No incluyas lo que cobrás del exterior.",
    )

    st.subheader("Situación personal")
    conyuge = st.checkbox("Tengo cónyuge a cargo")
    hijos   = st.slider("Hijos a cargo", min_value=0, max_value=10, value=0)
    gastos_mes = st.number_input(
        "Gastos profesionales deducibles (ARS/mes)",
        min_value=0,
        value=0,
        step=10_000,
        help="Solo aplica si sos Responsable Inscripto. Incluye equipamiento, software, servicios del exterior, alquiler de oficina, etc.",
    )

    st.subheader("Bienes Personales")
    saldo_ext = st.number_input(
        "Saldo cuentas del exterior al 31/12 (USD)",
        min_value=0,
        value=0,
        step=500,
        help="Total de fondos en cuentas del exterior al 31 de diciembre: Payoneer, Wise, cuentas bancarias en el exterior, etc.",
    )
    bienes_loc = st.number_input(
        "Otros bienes en Argentina (ARS)",
        min_value=0,
        value=0,
        step=500_000,
        help="Inmuebles, rodados, inversiones, cuentas bancarias locales, etc. Valor al 31/12.",
    )

inp = dict(
    ing_usd=ing_usd, tc=tc, ing_local_mes=ing_local_mes,
    conyuge=conyuge, hijos=hijos, gastos_mes=gastos_mes,
    saldo_ext=saldo_ext, bienes_loc=bienes_loc,
)
r = calcular_todo(**inp)
mono_gana = r["total_mono"] <= r["total_ri"]

with col_res:
    neto_usd_mes = r["neto"] / 12 / inp["tc"] if inp["tc"] > 0 else 0
    neto_mes_ars = r["neto"] / 12
    delta_th     = round(r["takehome_pct"] - 70, 1)
    delta_sign   = "+" if delta_th >= 0 else ""
    carga_pct    = round(100 - r["takehome_pct"], 1)

    st.markdown(
        # Card principal oscura
        f"<div style='background:#0f172a;border-radius:12px;padding:18px 22px 14px;margin-bottom:4px'>"

        # Neto mensual — el número protagonista
        f"<div style='color:#64748b;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px'>Neto mensual estimado</div>"
        f"<div style='display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:2px'>"
        f"  <span style='color:white;font-size:2em;font-weight:800;letter-spacing:-1px'>USD {neto_usd_mes:,.0f}</span>"
        f"  <span style='color:#475569;font-size:14px'>{ars(neto_mes_ars)}</span>"
        f"</div>"
        f"<div style='color:#4ade80;font-size:12px;font-weight:600;margin-bottom:14px'>"
        f"Take-home {r['takehome_pct']:.1f}% &nbsp;<span style='color:#475569;font-weight:400'>({delta_sign}{delta_th}pp vs relación de dependencia)</span>"
        f"</div>"

        # Separador
        f"<div style='border-top:1px solid #1e293b;margin-bottom:12px'></div>"

        # Ingreso bruto y carga fiscal en dos columnas
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px'>"
        f"  <div>"
        f"    <div style='color:#475569;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px'>Ingreso bruto / año</div>"
        f"    <div style='color:#94a3b8;font-size:1em;font-weight:700'>{ars(r['total_bruto'])}</div>"
        f"  </div>"
        f"  <div>"
        f"    <div style='color:#475569;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px'>Carga fiscal / año</div>"
        f"    <div style='color:#f87171;font-size:1em;font-weight:700'>{ars(r['total_mono'])} <span style='font-size:11px;color:#64748b;font-weight:400'>({carga_pct:.1f}%)</span></div>"
        f"  </div>"
        f"</div>"

        f"</div>",
        unsafe_allow_html=True,
    )

    # ---- DONUT: distribución fiscal ----
    if r["total_bruto"] > 0:
        d_labels, d_values, d_colors = [], [], []
        if r["neto"] > 0:
            d_labels.append("Neto"); d_values.append(r["neto"]); d_colors.append("#22c55e")
        if r["imp_gan"] > 0:
            d_labels.append("Ganancias"); d_values.append(r["imp_gan"]); d_colors.append("#f87171")
        if r["cuota_anual"] > 0:
            d_labels.append("Monotributo"); d_values.append(r["cuota_anual"]); d_colors.append("#60a5fa")
        if r["bp"] > 0:
            d_labels.append("Bienes Pers."); d_values.append(r["bp"]); d_colors.append("#a78bfa")

        fig = go.Figure(data=[go.Pie(
            labels=d_labels, values=d_values, hole=0.65,
            marker=dict(colors=d_colors, line=dict(color="white", width=3)),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} ARS<br>%{percent}<extra></extra>",
            sort=False,
        )])
        fig.add_annotation(
            text=f"<b>{r['takehome_pct']:.0f}%</b><br><span style='font-size:11px'>take-home</span>",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=18, color="#0f172a"), align="center",
        )
        # Leyenda manual como fila de chips debajo
        legend_html = "".join([
            f"<span style='display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:11px;color:#475569'>"
            f"<span style='width:10px;height:10px;border-radius:2px;background:{c};display:inline-block'></span>{l}</span>"
            for l, c in zip(d_labels, d_colors)
        ])
        fig.update_layout(
            showlegend=False,
            margin=dict(t=4, b=4, l=4, r=4),
            height=200,
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(
            f"<div style='text-align:center;margin-top:-8px;margin-bottom:4px'>{legend_html}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    filas_res = {
        "Deducciones Ganancias":    f"({ars(r['ded_total'])})",
        "Impuesto a las Ganancias": ars(r["imp_gan"]),
        "Cuota Monotributo anual":  (
            f"{ars(r['cuota_anual'])} (Cat. {r['cat']})" if r["cat"] else ":red[EXCEDE TOPE]"
        ),
        "Bienes Personales":        ars(r["bp"]),
    }
    for k, v in filas_res.items():
        c1, c2 = st.columns(2)
        c1.write(f"**{k}**")
        c2.write(v)

    st.markdown("---")

    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;"
        f"background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"
        f"padding:12px 18px;margin:4px 0'>"
        f"<span style='font-weight:600;font-size:1.05em;color:#0f172a'>Carga total / año</span>"
        f"<span style='font-weight:700;font-size:1.5em;color:#7c2d12'>{ars(r['total_mono'])}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)

    if not r["cat"]:
        st.error("**Pase a RI obligatorio** — ingresos locales superan tope Categoría H")
    elif mono_gana:
        ahorro = ars(r["total_ri"] - r["total_mono"])
        st.success(f"**Mantener Monotributo Cat. {r['cat']}** — ahorro vs RI: {ahorro}/año")
    else:
        ahorro = ars(r["total_mono"] - r["total_ri"])
        st.warning(f"**Evaluar RI** — potencial ahorro: {ahorro}/año con tus gastos actuales")

    st.caption("Factura E = cobro del exterior. No suma al tope de Monotributo.")

    # ---- ALERTA DE LÍMITE DE CATEGORÍA ----
    if r["cat"]:
        if r["loc_anual"] == 0:
            st.info(
                f"**Solo cobrás del exterior (Factura E):** quedás en Categoría **{r['cat']}** "
                f"sin importar cuánto facturés en USD. "
                f"Podés sumar hasta **{ars(r['tope_cat'])}** de ingresos locales antes de subir de categoría."
            )
        else:
            pct = r["pct_cat"]
            st.progress(min(pct, 1.0), text=f"Ingresos locales: {pct*100:.0f}% del tope de Cat. {r['cat']}")
            if r["cat_sig"]:
                margen_usd = r["margen_cat"] / inp["tc"] if inp["tc"] > 0 else 0
                extra_cuota = r["cuota_sig"] - r["cuota_cat"] if r["cuota_sig"] else 0
                if pct >= 0.85:
                    st.warning(
                        f"**Atención:** te quedan solo **{ars(r['margen_cat'])}/año** de margen local "
                        f"antes de pasar a Cat. {r['cat_sig']} (+{ars(extra_cuota)}/mes de cuota)."
                    )
                else:
                    st.caption(
                        f"Margen: **{ars(r['margen_cat'])}/año** (≈ USD {margen_usd:,.0f}/mes) "
                        f"de ingresos locales antes de pasar a Cat. {r['cat_sig']} (+{ars(extra_cuota)}/mes de cuota)."
                    )

    mono_c = "#16a34a" if mono_gana else "#b45309"
    ri_c   = "#b45309" if mono_gana else "#16a34a"
    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;font-size:0.9em;margin-top:6px'>"
        f"<thead><tr style='background:#f1f5f9'>"
        f"<th style='padding:7px 10px;text-align:left;color:#64748b;font-weight:600'></th>"
        f"<th style='padding:7px 10px;text-align:right;color:#64748b;font-weight:600'>Monotributo</th>"
        f"<th style='padding:7px 10px;text-align:right;color:#64748b;font-weight:600'>Resp. Inscripto</th>"
        f"</tr></thead><tbody>"
        f"<tr><td style='padding:6px 10px;color:#475569'>Ganancias</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(r['imp_gan'])}</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(r['imp_gan_ri'])}</td></tr>"
        f"<tr style='background:#f8fafc'><td style='padding:6px 10px;color:#475569'>Cuota / Honorarios</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(r['cuota_anual'])}</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(COSTO_CONTADOR_ANUAL)}</td></tr>"
        f"<tr><td style='padding:6px 10px;color:#475569'>Bienes Personales</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(r['bp'])}</td>"
        f"<td style='padding:6px 10px;text-align:right'>{ars(r['bp'])}</td></tr>"
        f"<tr style='border-top:2px solid #e2e8f0'>"
        f"<td style='padding:8px 10px;font-weight:700;color:#0f172a'>Total / año</td>"
        f"<td style='padding:8px 10px;text-align:right;font-weight:700;color:{mono_c}'>{ars(r['total_mono'])}</td>"
        f"<td style='padding:8px 10px;text-align:right;font-weight:700;color:{ri_c}'>{ars(r['total_ri'])}</td>"
        f"</tr></tbody></table>",
        unsafe_allow_html=True,
    )

# ============================================================
# SERVICIO MENSUAL
# ============================================================

st.divider()

st.markdown(
    "<div style='background:#0f172a;border-radius:10px;padding:22px 26px;margin:4px 0 20px 0'>"

    "<div style='color:white;font-weight:700;font-size:1.1em;margin-bottom:6px'>"
    "¿No tenés contador? Nosotros nos encargamos."
    "</div>"

    "<div style='color:#94a3b8;font-size:0.9em;margin-bottom:16px'>"
    "Este reporte te da el panorama. Liquidar correctamente, presentar las declaraciones "
    "y no perder vencimientos requiere seguimiento mensual. Eso es lo que ofrecemos."
    "</div>"

    "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:16px'>"

    "<div>"
    "<div style='color:#60a5fa;font-size:0.78em;font-weight:700;letter-spacing:.05em;margin-bottom:6px'>INCLUYE</div>"
    "<div style='color:#cbd5e1;font-size:0.85em;line-height:2em'>"
    "Liquidacion mensual del Monotributo<br>"
    "Recategorizacion automatica<br>"
    "DJ Ganancias y Bienes Personales<br>"
    "Alertas de vencimientos"
    "</div>"
    "</div>"

    "<div>"
    "<div style='color:#60a5fa;font-size:0.78em;font-weight:700;letter-spacing:.05em;margin-bottom:6px'>TAMBIEN</div>"
    "<div style='color:#cbd5e1;font-size:0.85em;line-height:2em'>"
    "Consultas ilimitadas por WhatsApp<br>"
    "Seguimiento de ingresos del exterior<br>"
    "Tarifa fija mensual sin sorpresas<br>"
    "Sin permanencia mínima"
    "</div>"
    "</div>"

    "</div>"

    "<div style='border-top:1px solid #1e293b;padding-top:12px;color:#93c5fd;font-size:0.88em'>"
    "Contacto: <a href='mailto:hola@contabilia.ar' style='color:white;font-weight:700;text-decoration:none'>hola@contabilia.ar</a>"
    " &nbsp;|&nbsp; Respondemos en menos de 24 hs"
    "</div>"

    "</div>",
    unsafe_allow_html=True,
)

# ============================================================
# GATE DE DESCARGA PDF
# ============================================================

st.divider()

col_pdf_desc, col_pdf_compra = st.columns([3, 2])

with col_pdf_desc:
    st.subheader("Descargá tu reporte personalizado")
    st.caption("Generado con tus datos — listo para compartir con tu contador")
    st.markdown(
        "<div style='display:flex;flex-direction:column;gap:6px;margin-top:8px'>"
        "<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>Liquidación completa</b> — Ganancias · Monotributo · Bienes Personales con tus deducciones</span></div>"
        "<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>Comparativa Mono vs RI</b> con ahorro estimado en pesos</span></div>"
        "<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>Neto mensual en ARS y USD</b> — take-home rate efectivo</span></div>"
        "<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>6 próximos pasos</b> para regularizar tu situación ante AFIP</span></div>"
        "<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>Hoja para tu contador</b> — datos listos para la primera reunión</span></div>"
        f"<div style='display:flex;gap:10px;align-items:flex-start'><span style='color:#22c55e;font-size:16px;flex-shrink:0'>✓</span><span><b>Calendario fiscal {YEAR}</b> — Monotributo · Ganancias · Bienes Personales</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )

with col_pdf_compra:
    st.markdown(
        "<div style='background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;"
        "padding:20px;text-align:center;margin-top:4px'>"
        "<div style='font-size:32px;margin-bottom:8px'>📄</div>"
        "<div style='font-weight:800;color:#1e40af;font-size:1.05em;margin-bottom:4px'>Reporte PDF completo</div>"
        "<div style='font-size:13px;color:#3b82f6;margin-bottom:12px'>Pago único · Sin suscripción</div>"
        "<div style='font-size:28px;font-weight:800;color:#0f172a;margin-bottom:4px'>USD 4.99</div>"
        "<div style='font-size:11px;color:#64748b'>Acceso inmediato por email</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.info("**¿No tenés código?**  \nComprá tu acceso en **contabilia.ar**")

col_pwd, col_btn = st.columns([2, 1])
with col_pwd:
    pwd = st.text_input("Código de acceso", type="password", placeholder="Ej: COMPRA001")
with col_btn:
    st.write("")
    st.write("")
    generar = st.button("Generar PDF", type="primary")

if generar:
    if not pwd:
        st.error("Ingresá tu código de acceso.")
    elif codigo_valido(pwd):
        with st.spinner("Generando reporte..."):
            pdf_bytes = generar_pdf(inp, r)
        nombre = f"reporte-fiscal-{datetime.date.today().isoformat()}.pdf"
        st.download_button(
            "⬇️ Descargar reporte PDF",
            data=pdf_bytes,
            file_name=nombre,
            mime="application/pdf",
            type="primary",
        )
        st.success("¡Listo! Hacé click en el botón para guardar el reporte.")
    else:
        st.error("Código inválido. Verificá tu compra o escribinos a hola@contabilia.ar")

st.caption(
    f"Valores aproximados basados en parámetros fiscales {YEAR}. "
    "No constituye asesoramiento contable, impositivo ni legal. "
    "Consultá con un contador habilitado."
)
