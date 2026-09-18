import unittest
from types import SimpleNamespace as NS
from datetime import datetime,timezone
from execution_safety import floor_volume,guard_entry,OrderRejected
from risk_guardian import RiskGuardian

NOW=datetime(2026,9,18,12,tzinfo=timezone.utc)

class Broker:
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1
    def __init__(self):
        self.account=NS(equity=1000.,balance=1000.,margin_free=900.)
        self.positions=[];self.deals=[];self.tick=NS(time=NOW.timestamp())
    def account_info(self):return self.account
    def symbol_info(self,symbol):return NS(volume_min=.01,volume_max=10.,volume_step=.01)
    def symbol_info_tick(self,symbol):return self.tick
    def positions_get(self):return self.positions
    def history_deals_get(self,*args):return self.deals
    def order_calc_profit(self,typ,symbol,volume,entry,exit):return (exit-entry)*100*volume*(1 if typ==0 else -1)
    def order_calc_margin(self,*args):return 50.

class Safety(unittest.TestCase):
    def setUp(self):
        self.b=Broker();self.req=dict(type=0,symbol='GOLD',volume=.2,price=2500.,sl=2480.,tp=2540.)
    def test_round_down_and_reject_minimum(self):
        self.assertEqual(floor_volume(.018,.017,.01,1,.01),.01)
        self.assertEqual(floor_volume(.01,.001,.01,1,.01),0)
        self.assertEqual(floor_volume(0,1,.01,1,.01),0)
    def test_risk_budget(self):
        with self.assertRaises(OrderRejected):guard_entry(self.b,self.req,True,now=NOW)
        self.req['sl']=2490
        result=guard_entry(self.b,self.req,True,now=NOW)
        self.assertEqual(result['volume'],.01)
        self.assertLessEqual(result['volume']*100*10*1.1,self.b.account.equity*.02)
    def test_disabled_stale_unknown(self):
        for enabled in [False]:
            with self.assertRaises(OrderRejected):guard_entry(self.b,self.req,enabled,now=NOW)
        self.b.tick.time-=90
        with self.assertRaisesRegex(OrderRejected,'scaduta'):guard_entry(self.b,self.req,True,now=NOW)
    def test_all_account_losses_count(self):
        self.b.deals=[NS(type=0,time=NOW.timestamp()-1,profit=-40.,commission=-1.,swap=0.)]
        with self.assertRaisesRegex(OrderRejected,'giornaliero'):guard_entry(self.b,self.req,True,now=NOW)
    def test_position_without_stop(self):
        self.b.positions=[NS(sl=0)]
        with self.assertRaisesRegex(OrderRejected,'senza stop'):guard_entry(self.b,self.req,True,now=NOW)
    def test_guardian_never_rounds_up(self):
        r=RiskGuardian(base_lot=.01,max_lot=.05,initial_equity=100,compounding_enabled=False)
        self.assertEqual(r._calc_lot({'lot_multiplier':1},100,20),0)
        self.assertEqual(r._round_lot(.019),.01)

class BacktestCausality(unittest.TestCase):
    def test_trailing_cannot_see_bar_close_early(self):
        from backtest_execution import simulate_exit
        bars=[{'o':100,'h':119,'l':95,'c':118},{'o':117,'h':118,'l':109,'c':110}]
        fill=simulate_exit(bars,0,2,100,90,140,True)
        self.assertEqual(fill['index'],1)
        self.assertEqual(fill['price'],111)
    def test_gap_and_timeout(self):
        from backtest_execution import simulate_exit
        self.assertEqual(simulate_exit([{'o':85,'h':92,'l':83,'c':90}],0,1,100,90,130,True)['price'],85)
        self.assertEqual(simulate_exit([{'o':100,'h':101,'l':99,'c':100}],0,1,100,90,130,True)['reason'],'time')
    def test_structural_stop_before_partial_target(self):
        from signals import ls_manage_step
        pos=dict(dir='buy',entry=100,sl=90,tp1=115,tp2=130,risk=10,part=False,booked=0,hh=100,ll=100)
        price,kind=ls_manage_step(pos,120,85,110,None,None,1)
        self.assertEqual(price,90)
        self.assertFalse(pos['part'])
        self.assertEqual(pos['booked'],0)

class Persistence(unittest.TestCase):
    def test_obsidian_keeps_personal_notes_and_legacy_file(self):
        import tempfile
        from pathlib import Path
        import obsidian_export as obs
        with tempfile.TemporaryDirectory(prefix='tradeflow-vault-test-') as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            obs.VAULT_PATH=temp
            obs.write_note('Journal','new','Generated v1',False)
            path=Path(temp)/'Journal'/'new.md'
            path.write_text(path.read_text()+'\nPersonal note\n')
            obs.write_note('Journal','new','Generated v2',False)
            self.assertIn('Personal note',path.read_text())
            self.assertIn('Generated v2',path.read_text())
            self.assertNotIn('Generated v1',path.read_text())
            legacy=Path(temp)/'Journal'/'legacy.md';legacy.write_text('Manual edits')
            obs.write_note('Journal','legacy','Generated',False)
            self.assertEqual(legacy.read_text(),'Manual edits')
            self.assertTrue(legacy.with_name('legacy.generated.md').exists())
    def test_trial_ledger_atomic_count(self):
        import tempfile,json
        from pathlib import Path
        import research_trials as rt
        original=rt.LEDGER_PATH
        with tempfile.TemporaryDirectory(prefix='tradeflow-ledger-test-') as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            try:
                rt.LEDGER_PATH=str(Path(temp)/'ledger.json')
                self.assertEqual(rt.record_trials(3),3)
                self.assertEqual(rt.record_trials(2),5)
                self.assertEqual(rt.total_trials(),5)
                with self.assertRaises(ValueError):rt.record_trials(-1)
            finally:rt.LEDGER_PATH=original

if __name__=='__main__':unittest.main()
