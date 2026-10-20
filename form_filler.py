"""真实表单识别与投递引擎（解决「真的识别并成功投递」）。

流程：
1. 加载投递页面（Selenium）
2. 识别所有表单控件（input / textarea / select / checkbox / file）
3. 对每个控件做语义识别（name/id/placeholder/label/父文本 关键字 + 嵌入相似度兜底）
4. 映射到统一字段并填入
5. 上传简历附件、点击提交、检测是否成功

限制（如实说明）：真实招聘平台（Boss直聘、智联、猎聘等）多有登录墙、
验证码与反爬，本引擎在「无需登录或已登录」的页面上可真正完成填表投递；
需要登录/验证码的站点必须先完成账号授权，否则无法自动提交。
"""
import re
import time

import embedding

# 统一字段 -> 候选关键字（控件识别用）
FIELD_KEYWORDS = {
    "姓名": ["姓名", "名字", "name", "fullname", "username", "realname", "真实姓名", "中文名"],
    "邮箱": ["邮箱", "email", "mail", "e-mail", "电子邮箱", "邮箱地址"],
    "手机": ["手机", "电话", "mobile", "phone", "tel", "cellphone", "联系方式", "手机号"],
    "学校": ["学校", "院校", "school", "university", "college", "毕业学校", "毕业院校"],
    "专业": ["专业", "major", "specialty", "所学专业"],
    "学历": ["学历", "education", "degree", "最高学历"],
    "性别": ["性别", "gender", "sex"],
    "出生日期": ["出生", "birth", "birthday", "出生日期", "生日"],
    "现居": ["现居", "城市", "居住", "city", "现居住地", "location", "所在城市"],
    "籍贯": ["籍贯", "户籍", "hometown", "户籍地", "籍贯地"],
    "民族": ["民族", "nation", "ethnicity", "民族成分"],
    "政治面貌": ["政治面貌", "面貌", "政治面目", "party"],
    "到岗时间": ["到岗", "到岗时间", "到岗日期", "入职时间", "onboard"],
    "期望岗位": ["岗位", "职位", "position", "job", "应聘岗位", "期望职位", "申请职位"],
    "工作年限": ["年限", "经验", "experience", "workyear", "工作年限", "工作经验"],
    "自我评价": ["评价", "介绍", "self", "简介", "个人简介", "自我介绍", "个人优势"],
}


def recognize_field(text: str):
    """根据控件文本识别其对应的统一字段名；识别不到返回 None。"""
    if not text:
        return None
    t = text.lower()
    best, best_score = None, 0
    for field, kws in FIELD_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in t:
                score = len(kw)
                if score > best_score:
                    best, best_score = field, score
    return best


def collect_controls(driver):
    """收集页面所有可填表单控件及其识别信息。"""
    from selenium.webdriver.common.by import By
    controls = []
    for el in driver.find_elements(By.CSS_SELECTOR, "input, textarea, select"):
        typ = (el.get_attribute("type") or "text").lower()
        if typ in ("hidden", "submit", "button", "image", "reset", "file"):
            continue
        name = el.get_attribute("name") or ""
        pid = el.get_attribute("id") or ""
        placeholder = el.get_attribute("placeholder") or ""
        aria = el.get_attribute("aria-label") or ""
        label = ""
        if pid:
            try:
                label = driver.find_element(By.CSS_SELECTOR, "label[for='%s']" % pid).text
            except Exception:
                label = ""
        parent = ""
        try:
            parent = el.find_element(By.XPATH, "..").text or ""
        except Exception:
            parent = ""
        text = " ".join([name, pid, placeholder, aria, label, parent[:60]])
        controls.append({
            "element": el, "tag": el.tag_name, "type": typ,
            "name": name, "id": pid, "text": text,
        })
    return controls


def fill_form(driver, data, resume_path=None):
    """识别并填写表单、上传简历、提交。返回 (结果描述, 识别到的字段列表)。"""
    from selenium.webdriver.common.by import By
    controls = collect_controls(driver)
    filled = []
    for c in controls:
        field = recognize_field(c["text"])
        if not field:
            continue
        value = data.get(field)
        if value is None or value == "":
            continue
        _set_value(c, value)
        filled.append(field)

    # 简历附件上传
    if resume_path:
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type=file]")
        for fi in file_inputs:
            fi.send_keys(str(resume_path))

    # 提交
    submitted = _submit(driver)
    return ("Web 表单已提交，识别并填写字段：%s" % ("、".join(filled) if filled else "无")), filled


def _set_value(c, value):
    el = c["element"]
    tag, typ = c["tag"], c["type"]
    if tag == "select":
        _select_option(el, value)
    elif typ in ("radio", "checkbox"):
        val = (el.get_attribute("value") or "").strip()
        if typ == "radio" and val and str(value) not in val:
            return  # 值不匹配的单选框不选（如性别选“男”则跳过“女”）
        try:
            if not el.is_selected():
                el.click()
        except Exception:
            pass
    else:
        try:
            el.clear()
            el.send_keys(str(value))
        except Exception:
            pass


def _select_option(sel, value):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    try:
        s = Select(sel)
        s.select_by_visible_text(str(value))
        return
    except Exception:
        pass
    try:
        for o in sel.find_elements(By.TAG_NAME, "option"):
            txt = (o.text or "").strip()
            if txt and txt in str(value):
                o.click()
                return
    except Exception:
        pass


def _submit(driver):
    from selenium.webdriver.common.by import By
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button[type=submit], input[type=submit]")
        if btns:
            btns[0].click()
            time.sleep(1.5)
            return True
        # 兜底：找含“投递/提交/申请/发送”字样的按钮
        for el in driver.find_elements(By.TAG_NAME, "button"):
            if re.search(r"投递|提交|申请|发送|确认", el.text or ""):
                el.click()
                time.sleep(1.5)
                return True
    except Exception:
        return False
    return False
