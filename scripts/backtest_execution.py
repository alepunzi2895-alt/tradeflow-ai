"""Causal OHLC exit simulation shared by standalone research engines.

Intrabar ambiguity: existing stop first. A close-derived trailing stop is only
effective on the next bar. Gaps through the stop fill at the worse opening price.
"""
def simulate_exit(candles,start,end,entry,stop,target,buy,be=True,trail_trigger=1.2):
    if start>=min(end,len(candles)):
        return None
    risk=abs(entry-stop)
    for index in range(start,min(end,len(candles))):
        c=candles[index]
        if (c['l']<=stop if buy else c['h']>=stop):
            return {'price':min(c['o'],stop) if buy else max(c['o'],stop),'index':index,'reason':'sl'}
        if (c['h']>=target if buy else c['l']<=target):
            return {'price':target,'index':index,'reason':'tp'}
        if be:
            profit=(c['c']-entry)*(1 if buy else -1)
            if profit>=risk*.8:
                proposed=entry+.2 if buy else entry-.2
                stop=max(stop,proposed) if buy else min(stop,proposed)
            if profit>=risk*trail_trigger:
                proposed=c['c']-risk*.7 if buy else c['c']+risk*.7
                stop=max(stop,proposed) if buy else min(stop,proposed)
    return {'price':candles[index]['c'],'index':index,'reason':'time'}
