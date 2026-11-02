import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from taskmap import demo_document

now = time.time()
specs = [
    ("review", "dev-server", "验收文档全文搜索", "让用户按正文查找文档", "搜索功能已提交：PR #123", "在测试环境验证完整搜索流程", 2),
    ("continue", "build-server", "修复应用自动更新", "让用户可靠地安装新版本", "已定位版本比较错误；尚未改代码", "修改版本比较规则后验证升级流程", 1),
    ("review", "release-server", "发布新版桌面应用", "确认用户可以安装并启动新版", "发布包构建成功，安装验收待进行", "在独立用户环境验证首次启动", 2),
    ("wait", "dev-server", "降低图片上传等待时间", "验证新上传方案的响应时间", "两组基准测试已进入队列", "查询基准测试的运行状态", 3),
    ("decision", "mac", "改善表单问答体验", "支持选择、输入和取消", "测试通过，等待体验确认", "体验一次完整问答流程", 2),
]
progress = ["PR 已提交；尚未做集成验证", "已定位版本比较错误；尚未改代码", "发布包已构建；停在安装验收", "基准测试已排队；尚未产出报告", "实现和测试通过；停在体验验收"]
tasks, conversations = [], []
for i, (kind, host, title, detail, evidence, action, priority) in enumerate(specs):
    cid = host + ":demo-" + str(i)
    conversation_title = ["文档检索功能", "自动更新排查", "桌面应用发布", "上传性能测试", "表单问答适配"][i]
    tasks.append(dict(id="demo-task-"+str(i), conversation_id=cid, semantic_key=kind+str(i), kind=kind, title=title, detail=detail, progress=progress[i], evidence=evidence,
        next_action=action, artifact="演示记录 · 非真实任务", priority=priority, confidence=0.94, status="open", created_at=now-3600, updated_at=now-900,
        snoozed_until=0, host=host, thread_id="demo-"+str(i), conversation_title=conversation_title, cwd="/workspace/example", path="/example/rollout.jsonl",
        summary=detail, conversation_updated_at=now-(i+1)*1200))
    conversations.append(dict(id=cid,host=host,thread_id="demo-"+str(i),title=conversation_title,cwd="/workspace/example",path="/example/rollout.jsonl",
        updated_at=now-(i+1)*1200,analysis_state="submitted",summary=detail,closed=0,active=False))
snapshot = dict(tasks=tasks,conversations=conversations,hosts=[dict(id=h,status="online",detail="演示数据",checked_at=now,total_files=0,remaining_files=0,root="") for h in ["mac","build-server","dev-server","release-server"]],
    settings=dict(automatic=True,interval_seconds=1800,idle_minutes=10,batch_size=6,history_days=0,enabled_hosts=["mac","build-server","dev-server","release-server"],source_limit=120,workdays_only=True,work_hours_enabled=False,work_start_minutes=540,work_end_minutes=1080),
    model="gpt-6-luna",effort="max",pending_analysis=0,last_sync=now-60,last_analysis=now-60,model_error="",sync=dict(running=False,phase=""))
snapshot["task_map"] = demo_document(tasks)
pathlib.Path(sys.argv[1]).write_text(json.dumps(snapshot,ensure_ascii=False))
