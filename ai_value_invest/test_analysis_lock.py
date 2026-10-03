import sys
import time

sys.path.insert(0, ".")
import main

P, F = 0, 0

def check(name, cond, extra=""):
    global P, F
    if cond:
        P += 1
        print("  [OK  ] %s%s" % (name, ("  ← " + extra) if extra else ""))
    else:
        F += 1
        print("  [FAIL] %s%s" % (name, ("  ← " + extra) if extra else ""))

acq = main._acquire_analysis_lock
rel = main._release_analysis_lock
TTL = main._ANALYSIS_LOCK_TTL

t1 = acq(9001)
check("首次抢占成功", t1 is not None, "token=%s" % t1)

t2 = acq(9001)
check("同一用户二次抢占被拒（返回 None）", t2 is None)

rel(9001, t1)
t3 = acq(9001)
check("释放后可再次抢占", t3 is not None and t3 != t1)

t_b = acq(9002)
check("另一用户不受影响（可同时分析）", t_b is not None)
rel(9001, t3)
rel(9002, t_b)

t4 = acq(9003)
t5 = acq(9003)
check("超时未释放的陈旧锁可被抢占（避免永久锁死）", t5 is not None)
rel(9003, t5)

t6 = acq(9004)
check("未超时的锁仍然拦得住", acq(9004) is None)
main._ANALYSIS_LOCKS.pop(9004, None)

t_old = acq(9005)
check("旧持有者释放不会误删新锁（token 校验）",
      main._ANALYSIS_LOCKS.get(9005) == t_new,
      "lock=%s new=%s" % (main._ANALYSIS_LOCKS.get(9005), t_new))
rel(9005, t_new)
check("新持有者正常释放后锁清空", 9005 not in main._ANALYSIS_LOCKS)

try:
    rel(9006, None)
    rel(9006, 123456.0)
    check("释放不存在的锁不抛异常", True)
except Exception as e:
    check("释放不存在的锁不抛异常", False, repr(e))

check("TTL 配置在 60~900 秒之间", 60 <= TTL <= 900, "TTL=%ss" % TTL)
check("锁表未残留测试数据",
      not ({9001, 9002, 9003, 9004, 9005, 9006} & set(main._ANALYSIS_LOCKS)),
      "残留 keys=%s" % sorted(set(main._ANALYSIS_LOCKS)))

print("----")
print("lock unit test: PASS %d / FAIL %d" % (P, F))
sys.exit(1 if F else 0)
