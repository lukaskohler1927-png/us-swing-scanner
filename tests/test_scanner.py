import copy
from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from swing import history, store
from swing.backtest import fingerprint
from swing.book import advance, choose, group, replay
from swing.data import SourceError
from swing.dolt import Dolt, FIELDS, Incomplete, SOURCE
from swing.edgar import Edgar
from swing.market import Listing, NY, bounds, directory, next_day, run_day, sessions
from swing.scan import actionable, full
from swing.strategy import STRATEGIES, candidates, clean, costs, event_match, features, proposal, triggers
from swing.telegram import TelegramFailure, dispatch, formatted, pair, reserve

N = datetime(2026,11,23,21,0,tzinfo=NY)
DAY = "2026-11-23"
INDEX = sessions("2025-08-01",DAY)


def fixture(index=INDEX, symbol_seed=4):
    rng = np.random.default_rng(symbol_seed)
    c = 70*np.exp(np.cumsum(rng.normal(.0004,.019,len(index))))
    op = c*np.exp(rng.normal(0,.005,len(c)))
    return pd.DataFrame({"open":op,"close":c,"high":np.maximum(c,op)*1.009,
                         "low":np.minimum(c,op)*.992,"volume":rng.integers(900000,2600000,len(c))},index=index)


def plan(side=1, **over):
    p = dict(day=DAY,asset="Aktie",side=side,name="Test",symbol="TEST",strategy=STRATEGIES[0],entry=100,
             lo=99,hi=101,stop=100-side*3,target=100+side*10,score=81,rr=2.2,spread=.001,
             reason="Test",version=fingerprint(),key="test-signal")
    return {**p,**over}


class Market(unittest.TestCase):
    def test_calendar(self):
        self.assertEqual(next_day("2026-11-25"),"2026-11-27")
        self.assertEqual(bounds("2026-11-27")[1].astimezone(NY).hour,13)
        self.assertEqual(bounds("2026-07-06")[1].hour,20)
        self.assertEqual(bounds(DAY)[1].hour,21)
        self.assertIsNone(run_day(N.replace(day=26),"scan"))
        self.assertIsNone(run_day(N.replace(hour=14),"scan"))
        self.assertEqual(run_day(N,"scan"),DAY)

    def test_directory(self):
        text=("ACT Symbol|Security Name|Exchange|ETF|Test Issue\n"
              "BRK.B|Class B Common Stock|N|N|N\nAB|AB Warrants|N|N|N\n"
              "AAA|AAA Ordinary Shares|A|N|N\nI|Index Fund|P|Y|N\nINV|Inverse 3X ETF|P|Y|N\n"
              "X|Test Common Stock|N|N|Y\nZ|Other Common Stock|Z|N|N\nFile Creation Time: 1123202606:00||||\n").encode()
        entries,_,_ = directory(text,"otherlisted",N,True)
        self.assertEqual(set(entries),{"BRK.B","AAA","I"})
        with self.assertRaises(ValueError):
            directory(text,"otherlisted",N+timedelta(days=7))
        with self.assertRaises(ValueError):
            directory(text.split(b"File Creation")[0],"otherlisted",N)

    def test_invalid_bars_and_duplicates(self):
        df=fixture().iloc[-4:].copy()
        df.iloc[0,df.columns.get_loc("low")]=100000
        d=pd.concat([df,df.iloc[[-1]].assign(volume=123)])
        out=clean(d,df.index)
        self.assertEqual(out.close.isna().sum(),2)

    def test_missing_data_and_future(self):
        df=fixture()
        a=features(clean(df,df.index))
        altered=df.copy()
        altered.loc[altered.index[-30:],"close"]*=2
        b=features(clean(altered,df.index))
        pd.testing.assert_frame_equal(a.iloc[:-30],b.iloc[:-30],check_dtype=False)
        hole=df.drop(df.index[-8])
        self.assertFalse(features(clean(hole,df.index)).ready.iloc[-1])

    def test_anonymous_feed_split_and_asof(self):
        provider = object.__new__(Dolt)
        provider.latest = DAY
        provider.ref = "a"*32
        provider.interval = lambda start,end,tab,*args: iter([[["2026-11-20","ABC"]]] if tab=="split" else
            [[["2026-11-19","ABC","80","81","79","80","5000"],["2026-11-20","ABC","40","41","39","40","10000"]]])
        provider.prepare(["ABC"],"2026-11-19",DAY,panel=True)
        bars = provider.bars(["ABC"],"2026-11-19",N)["ABC"]
        self.assertEqual(bars.close.iloc[0],80)
        self.assertTrue(pd.isna(bars.close.iloc[1]))
        with self.assertRaises(SourceError):
            provider.prepare(["ABC"],DAY,"2026-11-24")

    def test_truncated_query_rejected(self):
        provider = object.__new__(Dolt)
        provider.ref = "master"
        provider.reader = Mock()
        provider.reader.get.return_value = json.dumps({"data":{"columns":[],"rows":[],"status":"row_limit"}})
        with self.assertRaises(Incomplete):
            provider.query("SELECT 1",["n"])

    def test_bulk_integrity_and_weekly_cache(self):
        import gzip
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw, compact=root/"raw",root/"compact.gz"
            header=",".join(FIELDS)+"\n"
            row=DAY+",ABC,10,11,9,10,1000\n"
            raw.write_text(header+"2021-01-04,ABC,2,3,1,2,1000\n"+row*1001)
            history.compact(raw,compact,DAY,1001)
            self.assertEqual(len(gzip.decompress(compact.read_bytes()).splitlines()),1002)
            with self.assertRaises(SourceError):
                history.compact(raw,compact,DAY,1100)
            provider=Mock(latest=DAY,ref="v1")
            with patch.object(history,"ROOT",root):
                compact.rename(root/"prices.csv.gz")
                (root/"snapshot.json").write_text(json.dumps({"day":DAY,"revision":"v1"}))
                self.assertEqual(history.baseline(provider)[1]["day"],DAY)
                provider.query.assert_not_called()

    def test_catchup_time(self):
        self.assertEqual(run_day(N.replace(hour=7),"catchup"),"2026-11-20")
        self.assertIsNone(run_day(N.replace(hour=10),"catchup"))
        self.assertEqual(run_day(N.replace(day=27,hour=7),"catchup"),"2026-11-25")

    def test_news_and_edgar_cutoff(self):
        op,cl=bounds(DAY)
        h="ABC beats earnings estimates"
        self.assertTrue(event_match([(op,h,"")],1,op-timedelta(days=1),cl))
        self.assertFalse(event_match([(cl+timedelta(seconds=1),h,"")],1,op,cl))
        self.assertFalse(event_match([(op,"ABC could beat estimates","")],1,op-timedelta(days=1),cl))
        self.assertFalse(event_match([(op,h,"")],-1,op-timedelta(days=1),cl))
        rows=dict(form=["8-K"],items=["2.02,9.01"],acceptanceDateTime=[op.isoformat()],accessionNumber=["0001-01-0001"])
        self.assertTrue(Edgar.find(rows,1,op-timedelta(days=1),cl))
        self.assertFalse(Edgar.find(rows,1,op,cl))


class Trading(unittest.TestCase):
    def test_both_sides_all_rules(self):
        # Fixtures for every directional trigger independently of the historical study.
        for side in (1,-1):
            for i,strategy in enumerate(STRATEGIES):
                r=dict(open=100-side*.4,close=100,prev=100-side*2,prev_o=100-side*1.5,
                       e20=100-side*.2,e50=100-side*1.2,e200=100-side*2,slope=side,
                       hist=side*.2,last_hist=-side*.1,low=99.5,high=100.5,lo20=93,hi20=107,
                       rsi=35 if side==1 else 65,last_rsi=30 if side==1 else 70,
                       gap=side*.03,rv=2,dollar=9e7,atr=1,ready=True,
                       lo3=99.1,hi3=100.9,lo60=92,hi60=108)
                if i==0:
                    r["hi20" if side==1 else "lo20"]=100-side*.1
                f=pd.DataFrame([r],index=[pd.Timestamp(DAY)])
                self.assertTrue(triggers(f,side)[strategy].iloc[0],(side,strategy))
                event={"keyword":"earnings","at":N.isoformat(),"url":""} if i==4 else None
                p=proposal(f.iloc[0],strategy,side,event=event)
                self.assertIsNotNone(p,(side,strategy))
                worst=p["hi"] if side==1 else p["lo"]
                self.assertGreaterEqual((side*(p["target"]-worst)-costs(worst,side))/(side*(worst-p["stop"])+costs(worst,side)),2)
                self.assertEqual(p["score"],sum(p["components"]))
                self.assertLessEqual(p["score"],100)

    def test_simultaneous_stop_and_target(self):
        for s in (1,-1):
            p=plan(s)
            out=advance(p,DAY,dict(open=100,low=85,high=115,close=105))
            self.assertEqual(out["status"],"STOP")
            self.assertLess(out["realized_r"],0)

    def test_gap_and_expiry(self):
        p=plan()
        self.assertEqual(advance(p,DAY,dict(open=102,high=103,low=99,close=100))["status"],"EXPIRED")
        self.assertIsNone(advance(p,DAY,dict(open=100,high=101,low=99,close=100)))
        out=advance(p,next_day(DAY),dict(open=92,high=99,low=90,close=95))
        self.assertEqual(out["out"],92)
        self.assertLess(out["net"],-8)

    def test_divided_replay(self):
        dates=INDEX[-10:]
        days=[str(d.date()) for d in dates]
        bars=pd.DataFrame({"open":100.,"low":99.,"high":101.,"close":100.},index=dates)
        plans={d:[plan(day=d)] for d in days}
        res=replay(dates,plans,{"TEST":bars})
        self.assertEqual(res["signals"],1)
        self.assertEqual(res["n"],1)
        self.assertLess(res["equity_end"],100000)
        self.assertTrue(res["max_drawdown"]>0)
        self.assertEqual(len(choose([plan(),plan(-1)])),1)

    def test_twenty_signals_per_session_with_separate_portfolio_budget(self):
        dates = INDEX[-10:]
        bars = pd.DataFrame(dict(open=100.,low=99.,high=101.,close=100.),index=dates)
        rows, frames = {}, {}
        for day_number, d in enumerate(dates[:2]):
            day = str(d.date())
            rows[day] = []
            for rank in range(25):
                symbol = f"X{day_number}{rank:02}"
                frames[symbol] = bars
                rows[day].append(plan(1 if rank%2==0 else -1,symbol=symbol,day=day,score=99-rank))
        result = replay(dates,rows,frames)
        self.assertEqual(result["signals"],40)
        self.assertEqual(result["signal_fills"],40)
        self.assertEqual(result["n"],9)
        self.assertEqual(result["unfunded_fills"],31)

    def test_gate(self):
        p=plan()
        state=store.blank()
        self.assertFalse(actionable(p,state,N))
        good=dict(n=40,pf=1.3,avg_r=.2)
        state["validation"]=dict(fingerprint=fingerprint(),source=SOURCE,last=DAY,
                                 oos={**good,"unknown":0,"groups":{group(p):good}})
        state["days"]=[{"day":str(d.date()),"version":p["version"]} for d in INDEX[-20:]]
        state["closed"]=[dict(p,net=2 if i%2 else -1,realized_r=.8 if i%2 else -.4) for i in range(40)]
        with patch.dict(os.environ,{"LIVE_ALERTS":"true"}):
            self.assertTrue(actionable(p,state,N))
            self.assertFalse(actionable(dict(p,spread=None),state,N))
            self.assertFalse(actionable(plan(-1),state,N))
            self.assertFalse(actionable(p,state,N+timedelta(days=50)))


class Pipeline(unittest.TestCase):
    def test_transient_checkpoint_rejection(self):
        env={"STATE_KEY":"x"*32,"PUBLISH_LEDGER":"1","DEFAULT_BRANCH":"main"}
        with tempfile.TemporaryDirectory() as d, patch.object(store,"ROOT",Path(d)), patch.dict(os.environ,env), \
                patch("swing.store.time.sleep") as sleep, patch("swing.store.subprocess.run") as git:
            git.side_effect=[Mock(returncode=0),Mock(returncode=0),Mock(returncode=1),Mock(returncode=0)]
            store.save(store.blank())
            self.assertEqual(git.call_args_list[-1],git.call_args_list[-2])
            self.assertNotIn("--force",git.call_args.args[0])
            sleep.assert_called_once_with(2)

    def test_encrypted_restart_and_uncertain_delivery(self):
        with tempfile.TemporaryDirectory() as d, patch.object(store,"ROOT",Path(d)), patch.dict(os.environ,{"STATE_KEY":"x"*40,"PUBLISH_LEDGER":"0"}):
            state = store.blank()
            state["chat"]=1234567
            reserve(state,"x","Private Testnachricht")
            reserve(state,"x","doppelt")
            with patch("swing.telegram.api",side_effect=TelegramFailure("test")) as send:
                with self.assertRaises(TelegramFailure):
                    dispatch(state,store.save,lambda:N)
                state=store.read()
                dispatch(state,store.save,lambda:N)
                self.assertEqual(send.call_count,1)
            self.assertNotIn(b"Private Testnachricht",(Path(d)/"ledger.enc").read_bytes())
            self.assertEqual(state["outbox"][0]["status"],"uncertain")

    def test_repeat_manual_pair_test(self):
        from swing.cli import run
        state=store.blank()
        state["chat"]=17
        with patch("swing.cli.store.read",return_value=state), patch("swing.cli.store.save"), \
                patch("swing.cli.publish_status"), patch("swing.telegram.api",return_value={"message_id":1}) as send:
            for run_id, attempt in [("101","1"),("101","1"),("101","2"),("102","1")]:
                with patch.dict(os.environ,{"GITHUB_RUN_ID":run_id,"GITHUB_RUN_ATTEMPT":attempt}):
                    run("pair-test")
            self.assertEqual(send.call_count,3)
            self.assertEqual(len(state["outbox"]),3)

    def test_pair_and_expired_send(self):
        secret="p"*24
        msg=dict(date=N.timestamp(),text="/start "+secret,chat={"type":"private","id":4},**{"from":{"id":4}})
        state=store.blank()
        with patch.dict(os.environ,{"TELEGRAM_PAIR_CODE":secret}), patch("swing.telegram.api",return_value=[{"message":msg}]):
            pair(state,N)
        self.assertEqual(state["chat"],4)
        reserve(state,"old","expired",expires=(N-timedelta(seconds=1)).isoformat())
        with patch("swing.telegram.api") as send:
            dispatch(state,lambda s:None,lambda:N)
            send.assert_not_called()

    def test_full_forward_workflow(self):
        head=fixture()
        # Realistic OHLCV, deterministic technical breakout on last bar.
        x=np.arange(len(head))
        c=100+.07*x+np.sin(x/4)*1.6
        head["close"]=c
        head["open"]=c-.2
        head["high"]=c+.75
        head["low"]=c-.75
        head["volume"]=1000000
        head.iloc[-13,head.columns.get_loc("low")] -= 2.5
        close=float(head.high.tail(21).max()+.35)
        head.iloc[-1]=pd.Series(dict(open=close-.4,close=close,low=close-.65,high=close+.45,volume=2200000))[head.columns]
        # Risk plan uses prior three lows. Bring the final three supports near the breakout.
        for j in [-4,-3,-2]:
            z=close-.52-abs(j)*.03
            head.iloc[j]=pd.Series(dict(open=z-.12,close=z,low=z-.38,high=z+.18,volume=1000000))[head.columns]
        provider=Mock()
        provider.bars.side_effect=lambda syms,first,end:{"TEST":head.loc[first:]} if syms else {}
        provider.ref=provider.base_revision="test-revision"
        state=store.blank()
        state["chat"]=17
        with patch("swing.scan.universe",return_value=({"TEST":Listing("TEST","Test","NASDAQ","Aktie")},{})), patch.dict(os.environ,{"PAPER_TELEGRAM":"true","LIVE_ALERTS":"false","SEC_USER_AGENT":""}):
            report=full(Mock(),provider,state,DAY,N)
            self.assertEqual(report["selected"],1,report)
            self.assertEqual(len(state["outbox"]),1)
            self.assertIn("PAPER",state["outbox"][0]["text"])
            self.assertIsNone(full(Mock(),provider,state,DAY,N))
            with patch("swing.telegram.api",return_value={"message_id":1}):
                dispatch(state,lambda s:None,lambda:N)
            self.assertIn("Spread unbekannt",state["outbox"][0]["text"])
            from swing.scan import reconcile
            tomorrow=pd.Timestamp(next_day(DAY))
            head.loc[tomorrow]=pd.Series(dict(open=close*1.12,close=close*1.12,low=close*1.10,high=close*1.13,volume=1000000))[head.columns]
            reconcile(state,{"TEST":head},str(tomorrow.date()),fingerprint())
            self.assertEqual(state["closed"][0]["status"],"EXPIRED")
            self.assertEqual(state["outbox"][-1]["kind"],"invalidation")

    def test_twenty_ranked_distinct_telegram_signals_with_nine_open(self):
        symbols = [f"X{i:02}" for i in range(35)]
        listings = {s:Listing(s,s,"NASDAQ","Aktie") for s in symbols}
        bars = pd.DataFrame(dict(open=100.,high=101.,low=99.,close=100.,volume=1000000),index=INDEX)
        provider = Mock()
        provider.bars.side_effect = lambda batch,first,end: {s:bars.loc[first:] for s in batch}
        provider.ref = provider.base_revision = "test"
        state = store.blank()
        state["chat"] = 17
        state["active"] = [plan(symbol=s,day=str(INDEX[-2].date())) for s in symbols[:9]]

        def proposals(symbol,*args):
            i = symbols.index(symbol)
            side = 1 if i%2 else -1
            return [plan(side,symbol=symbol,score=100-i),plan(-side,symbol=symbol,score=50-i)]

        with patch("swing.scan.universe",return_value=(listings,{})), \
                patch("swing.scan.candidates",side_effect=proposals), \
                patch.dict(os.environ,{"SEC_USER_AGENT":"","PAPER_TELEGRAM":"true"}):
            report = full(Mock(),provider,state,DAY,N)
        self.assertEqual((report["selected"],report["selected_long"],report["selected_short"]),(20,10,10))
        self.assertEqual([p["symbol"] for p in state["active"]],symbols[:29])
        self.assertEqual(len({m["key"] for m in state["outbox"]}),20)
        self.assertIsNone(full(Mock(),provider,state,DAY,N))

    def test_missing_coverage_blocks_publication(self):
        provider=Mock()
        provider.bars.return_value={}
        with patch("swing.scan.universe",return_value=({"T":Listing("T","Test","NYSE","Aktie")},{})):
            with self.assertRaises(SourceError):
                full(Mock(),provider,store.blank(),DAY,N)
