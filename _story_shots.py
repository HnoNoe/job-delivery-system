"""技术叙事截图脚本：驱动真实浏览器走完六步流程，按叙事顺序截 12 张图到 docs/story/。

前置：主应用(8501)与 mock 站(5001)已启动。运行：python _story_shots.py
"""
import os
import time

from DrissionPage import ChromiumPage, ChromiumOptions

BASE = "http://127.0.0.1:8501"
MOCK = "http://127.0.0.1:5001"
OUT = os.path.join("docs", "story")

co = ChromiumOptions().headless()
co.auto_port()
co.set_argument("--window-size", "1500,950")
co.set_argument("--force-device-scale-factor", "1")
page = ChromiumPage(co)


def shot(name, wait=1.2):
    time.sleep(wait)
    page.get_screenshot(path=OUT, name=name)
    print("saved:", name)


def wait_idle(timeout=120):
    """等 Streamlit 跑完当前脚本（右上角 Stop 消失）。"""
    for _ in range(int(timeout / 2)):
        if not page.ele('xpath://button[contains(.,"Stop")]', timeout=0.6):
            return True
        time.sleep(2)
    print("!! wait_idle 超时")
    return False


def wait_text(text, timeout=90):
    for _ in range(int(timeout / 2)):
        if page.ele('xpath://*[contains(text(),"%s")]' % text, timeout=0.6):
            return True
        time.sleep(2)
    print("!! 未等到文本:", text)
    return False


def btn(text, timeout=10):
    return page.ele('xpath://button[contains(., "%s")]' % text, timeout=timeout)


def click_btn(text, wait_after=2.5, timeout=10):
    btn(text, timeout).click()
    time.sleep(wait_after)


def see(text, timeout=8):
    """把包含指定文字的元素滚动到视口顶部。"""
    e = page.ele('xpath://*[contains(text(), "%s")]' % text, timeout=timeout)
    if not e or not e.states.is_displayed:
        print("!! see 未找到:", text)
        return
    try:
        page.run_js("arguments[0].scrollIntoView({block:'start'})", e)
    except Exception as exc:
        print("!! see 滚动失败:", text, exc)
    time.sleep(0.8)


def click_until_started(text, tries=3):
    """点按钮并确认 Streamlit 真的开始跑（Stop 出现）；没跑起来就重试。"""
    for i in range(tries):
        btn(text, timeout=15).click()
        time.sleep(4)
        if page.ele('xpath://button[contains(.,"Stop")]', timeout=1):
            return True
        print("!! 点击未生效，重试 %d: %s" % (i + 1, text))
    return False


def top():
    page.run_js("window.scrollTo(0,0)")
    time.sleep(0.6)


try:
    # ---- 01 落地首屏 ----
    page.get(BASE)
    time.sleep(7)
    top()
    shot("01-hero.png")

    # ---- 02 步骤① 表单（样本数据自动填充） ----
    see("基本信息")
    shot("02-form.png")

    # ---- 确认信息 → 步骤② ----
    click_btn("✅ 确认信息，进入下一步", 3)

    # 勾选 Mock、取消 Boss
    page.ele('xpath://label[contains(.,"Boss直聘")]', timeout=8).click()
    time.sleep(1.5)
    page.ele('xpath://label[contains(.,"Mock测试站")]', timeout=8).click()
    time.sleep(1.5)
    see("平台与登录")
    shot("03-step2.png")

    # ---- 03 网页内扫码面板 ----
    btn("📱 网页内扫码", timeout=15).click()
    # 隐藏浏览器启动 + 面板渲染需要时间，轮询面板里的按钮出现
    _qr_btn = None
    for _ in range(25):
        time.sleep(2)
        _qr_btn = page.ele('xpath://button[contains(.,"模拟手机扫码")]', timeout=1)
        if _qr_btn:
            break
    see("扫码登录")
    shot("04-qr-panel.png")

    # ---- 04 模拟扫码 → 登录成功（面板自动收起） ----
    if _qr_btn:
        _qr_btn.click()
        for _ in range(10):
            time.sleep(2)
            if not page.ele('xpath://button[contains(.,"模拟手机扫码")]', timeout=1):
                break
    else:
        print("!! 扫码面板未打开，跳过模拟扫码")
    top()
    shot("05-login-done.png")

    # ---- 05 检索岗位 ----
    see("检索岗位")
    click_until_started("🔍 开始检索")
    if not wait_text("共检索到", 150):  # ✅ 共检索到 N 个岗位
        shot("06-debug.png", 0)
    wait_idle(60)
    see("共检索到")
    shot("06-jobs.png")

    # ---- 06 准备投递材料 ----
    see("准备投递材料")
    click_until_started("🚀 准备投递材料")
    if not wait_text("个岗位准备好", 150):  # ✅ 已为 N 个岗位准备好…
        shot("07-debug.png", 0)
    wait_idle(60)
    see("个岗位准备好")
    shot("07-materials.png")

    # ---- 07 三维匹配空间工作台 ----
    see("投递与反馈")
    time.sleep(7)  # 自定义组件 iframe 渲染
    shot("08-workbench.png")

    # ---- 08 任务卡片 ----
    see("推荐理由", timeout=20)
    shot("09-task-cards.png")

    # ---- 09 安全模式投递 → 确认手动投递 → 标记进面试 ----
    btn("查看投递材料", timeout=20).click()
    wait_idle(30)
    btn("确认已手动投递", timeout=15).click()
    wait_idle(30)
    btn("✅ 进面试", timeout=15).click()
    wait_idle(30)
    see("投递与反馈")
    shot("10-feedback.png")

    # ---- 10 再画像再匹配（式三δ生效，反馈前后对比） ----
    if page.ele('xpath://button[contains(.,"用新画像重新匹配")]', timeout=5):
        btn("用新画像重新匹配").click()
        wait_text("式三间隔特征已启用", 90)
        wait_idle(60)
        see("画像演进")
        shot("11-rematch.png")
    else:
        print("!! 未找到再匹配按钮，跳过")

    # ---- 11 画像广场 ----
    page.get(BASE + "/%E7%94%BB%E5%83%8F%E5%B9%BF%E5%9C%BA")
    time.sleep(9)
    shot("12-square.png")

    # ---- 12 mock 站 ----
    page.get(MOCK + "/web/geek/job?query=%E5%90%8E%E7%AB%AF&city=%E5%8C%97%E4%BA%AC&page=1")
    time.sleep(4)
    shot("13-mock-site.png")

    print("\n=== 全部截图完成 ===")
finally:
    page.quit()
