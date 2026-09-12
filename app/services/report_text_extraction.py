import re
from app.services.reporting_common import metric_value


def suggested_metrics(text):
    result=[]
    for key,pattern in [('vehicles_total',r'TOTAL\s+VE[IÍ]CULOS\s*:?\s*(\d+)'),('seized_vehicles',r'VIATURAS\s+APREENDIDAS\s*:?\s*(\d+)'),('revenue',r'(?:RECEITA\s+TOTAL|TOTAL\s+RECEITA)\s*:?\s*([\d.,]+)')]:
        found=re.search(pattern,text,re.I)
        if found:
            try:result.append({'key':key,'dimension':'Geral','value':str(metric_value(key,found[1]))})
            except Exception:continue  # Uncertain OCR is reviewed as text, never invented as a value.
    return result
