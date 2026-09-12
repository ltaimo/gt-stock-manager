"""Small exportable charts from confirmed daily observations, with visible gaps."""
from datetime import date
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

def metric_chart(metric):
    points=metric['trend']
    image=Image.new('RGB',(1100,340),'white');draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype('DejaVuSans.ttf',20)
    except OSError:font=ImageFont.load_default(size=20)
    left,top,right,bottom=110,35,1050,290
    maximum=max(float(p['value']) for p in points) or 1
    first=date.fromisoformat(points[0]['date']);last=date.fromisoformat(points[-1]['date']);span=max(1,(last-first).days)
    for step in range(5):
        y=bottom-(bottom-top)*step/4
        draw.line((left,y,right,y),fill='#e5e5e5',width=1)
        draw.text((4,y-12),f'{maximum*step/4:,.1f}',fill='#454545',font=font)
    previous=None
    for i,p in enumerate(points):
        day=date.fromisoformat(p['date']);x=left+(right-left)*(day-first).days/span;y=bottom-(bottom-top)*float(p['value'])/maximum
        if previous and (day-previous[2]).days==1:draw.line((previous[0],previous[1],x,y),fill='#aa8500',width=4)
        draw.ellipse((x-5,y-5,x+5,y+5),fill='#aa8500')
        if i%max(1,len(points)//6)==0 or i==len(points)-1:draw.text((x-25,bottom+12),day.strftime('%d/%m'),fill='#454545',font=font)
        previous=x,y,day
    out=BytesIO();image.save(out,format='PNG');return out.getvalue()
