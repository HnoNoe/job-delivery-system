"""招聘平台注册表：平台 -> 登录页/二维码选择器/搜索页/列表选择器/登录检测。

真实平台配置为「基于公开结构的最佳起始配置」，接真实平台时需实测扫码验证并微调
（平台改版、反爬会变）。

每个平台字段：
- login_url: 登录页 URL
- login_qr_selector: 二维码元素 CSS 选择器（img/canvas/div）
- search_url: 搜索页 URL 模板，占位符 {keyword}/{city}/{page}
- item_selector: 岗位条目选择器
- fields: 字段名 -> CSS 选择器（相对条目）
- login_check: 登录态检测方式 {"type":"cookie","name":...} / {"type":"url_not_contains","value":...}
- headless_ok: 无头模式是否可用（真实平台通常需有头）
"""

PLATFORMS = {
    "mock": {
        "name": "Mock测试站",
        "login_url": "http://127.0.0.1:5001/web/user/",
        "login_qr_selector": "img.qrcode-img",
        "search_url": "http://127.0.0.1:5001/web/geek/job?query={keyword}&city={city}&page={page}",
        "item_selector": "li.job-card-wrapper",
        "fields": {
            "岗位名称": ".job-name",
            "单位名称": ".company-name",
            "岗位链接": ".job-card-body a",
            "城市": ".job-area",
        },
        "login_check": {"type": "url_not_contains", "value": "web/user"},
        "headless_ok": True,
        "api_url": "http://127.0.0.1:5001/wapi/zpgeek/search/joblist.json?query={keyword}&city={city}&page={page}&pageSize=30",
        "api_listen_kw": "joblist.json",
        "api_jobs_path": "zpData.jobList",
        "api_field_map": {
            "岗位名称": "jobName",
            "单位名称": "brandName",
            "城市": "cityName",
            "行业": "brandIndustry",
            "薪资": "salaryDesc",
            "学历": "jobDegree",
            "经验": "jobExperience",
            "技能": "skills",
            "岗位描述": "jobLabels",
            "岗位链接": "encryptJobId",
            "公司": "brandName",
            "已沟通": "contact",
            "投递入口类型": "entryType",
            "投递入口地址": "entryAddr",
        },
    },
    "boss": {
        "name": "Boss直聘",
        "login_url": "https://www.zhipin.com/web/user/?ka=header-login",
        "login_qr_selector": "img.qrcode-img, canvas.qrcode-canvas, .qrcode img",
        "search_url": "https://www.zhipin.com/web/geek/job?query={keyword}&city={city}&page={page}",
        "item_selector": "li.job-card-wrapper",
        "fields": {
            "岗位名称": ".job-name",
            "单位名称": ".company-name",
            "岗位链接": ".job-card-body a",
            "城市": ".job-area",
            "岗位描述": ".job-info",
        },
        "login_check": {"type": "url_not_contains", "value": "web/user"},
        "headless_ok": False,
        "api_url": "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query={keyword}&city={city}&page={page}&pageSize=30",
        "api_listen_kw": "joblist.json",
        "api_jobs_path": "zpData.jobList",
        "api_field_map": {
            "岗位名称": "jobName",
            "单位名称": "brandName",
            "城市": "cityName",
            "行业": "brandIndustry",
            "薪资": "salaryDesc",
            "学历": "jobDegree",
            "经验": "jobExperience",
            "技能": "skills",
            "岗位描述": "jobLabels",
            "岗位链接": "encryptJobId",
            "公司": "brandName",
            "已沟通": "contact",
        },
    },
    "zhilian": {
        "name": "智联招聘",
        "login_url": "https://passport.zhaopin.com/login",
        "login_qr_selector": "img.qrcode, .qr-code img, canvas",
        # sou.zhaopin.com 会 302 到 www.zhaopin.com/jobs/，新页面结构见下方选择器
        "search_url": "https://www.zhaopin.com/jobs/?jl={city}&kw={keyword}&p={page}",
        "item_selector": "div.job-card",
        "fields": {
            "岗位名称": ".job-card__title-main",
            "单位名称": ".job-card__company-name",
            "城市": ".job-card__location",
            "薪资": ".job-card__salary",
        },
        "dom_parse": True,
        "login_check": {"type": "cookie", "name": "at"},
        "headless_ok": False,
    },
    "lagou": {
        "name": "拉勾",
        "login_url": "https://passport.lagou.com/login/login.html",
        "login_qr_selector": "img.qr_code_img, .qrcode img, canvas",
        "search_url": "https://www.lagou.com/wn/zhaopin?pageNo={page}&city={city}&kd={keyword}",
        "item_selector": "li.con_list_item",
        "fields": {
            "岗位名称": ".p_top a h3",
            "单位名称": ".company_name a",
            "岗位链接": ".p_top a",
            "城市": ".add em",
            "岗位描述": ".li_b_l",
        },
        "login_check": {"type": "cookie", "name": "LGRID"},
        "headless_ok": False,
        "api_url": "https://www.lagou.com/jobs/positionAjax.json?city={city}&needAddtionalResult=false&kd={keyword}&pn={page}",
        "api_listen_kw": "positionAjax.json",
        "api_jobs_path": "content.positionResult.result",
        "api_field_map": {
            "岗位名称": "positionName",
            "单位名称": "companyFullName",
            "城市": "city",
            "薪资": "salary",
            "学历": "education",
            "经验": "workYear",
            "公司": "companyFullName",
            "岗位链接": "positionId",
        },
    },
    "liepin": {
        "name": "猎聘",
        "login_url": "https://www.liepin.com/login",
        "login_qr_selector": "img.login-qrcode, .qrcode img, canvas",
        # 猎聘的城市参数是 dqs（不是 city），值见 LIE_PIN_CITY_CODES
        "search_url": "https://www.liepin.com/zhaopin/?key={keyword}&dqs={city}&page={page}",
        "item_selector": "div.jobCardPcContainer",
        "fields": {
            "岗位名称": "div.jobTitleBox div.ellipsis-1",
            "单位名称": ".companyName",
            "岗位链接": 'a[data-nick="job-detail-job-info"]',
            "城市": "div.jobTitleBox span.ellipsis-1",
        },
        # 搜索结果是前端渲染的，requests 拿不到岗位卡片，必须走浏览器 DOM
        "dom_parse": True,
        "login_check": {"type": "url_not_contains", "value": "login"},
        "headless_ok": False,
    },
    "job51": {
        "name": "前程无忧",
        "login_url": "https://login.51job.com/",
        "login_qr_selector": "img.qrcode, .login-qrcode img, canvas",
        # 51job 的城市参数用 6 位城市码，值见 JOB51_CITY_CODES
        "search_url": "https://we.51job.com/pc/search?jobArea={city}&keyword={keyword}&pageNum={page}",
        "item_selector": "div.joblist-item",
        "fields": {
            "岗位名称": ".joblist-item-jobname",
            "单位名称": ".cname",
            "岗位链接": ".joblist-item-jobname",
            "城市": ".joblist-item-jobinfo",
        },
        # 前端渲染 + 岗位链接要由 sensorsdata 的 jobId 拼，不能只靠 CSS 选择器
        "dom_parse": True,
        "login_check": {"type": "url_not_contains", "value": "login"},
        "headless_ok": False,
        "api_url": "https://we.51job.com/api/job/search-pc?api_key=51job&keyword={keyword}&searchType=2&pageNum={page}&jobArea={city}",
        "api_listen_kw": "search-pc",
        "api_jobs_path": "resultbody.job.items",
        "api_field_map": {
            "岗位名称": "jobName",
            "单位名称": "fullCompanyName",
            "城市": "jobAreaString",
            "薪资": "provideSalaryString",
            "学历": "degreeString",
            "经验": "workYearString",
            "公司": "fullCompanyName",
            "岗位链接": "jobId",
        },
    },
}


def get(platform_key):
    return PLATFORMS.get(platform_key)


# 登录态联网检测：带保存的 cookie 访问"需要登录"的页面，看是否被跳回登录页。
# 只用于判断登录是否有效，不抓取数据、不改动账号。
AUTH_PROBES = {
    "boss": {"url": "https://www.zhipin.com/web/chat/index"},
    "zhilian": {"url": "https://i.zhaopin.com/"},
    "lagou": {"url": "https://www.lagou.com/wn/resume/myresume"},
    "liepin": {"url": "https://c.liepin.com/"},
    "job51": {"url": "https://i.51job.com/"},
}

for _key, _probe in AUTH_PROBES.items():
    if _key in PLATFORMS:
        PLATFORMS[_key]["auth_probe"] = _probe


def names():
    return [(k, v["name"]) for k, v in PLATFORMS.items()]


# 各平台 cookie 域名（用于读取用户真实浏览器登录态）
COOKIE_DOMAINS = {
    "boss": "zhipin.com",
    "zhilian": "zhaopin.com",
    "lagou": "lagou.com",
    "liepin": "liepin.com",
    "job51": "51job.com",
}


# Boss直聘 城市码（意向城市名 -> 城市编码）
BOSS_CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100",
    "武汉": "101200100", "南京": "101190100", "西安": "101110100",
    "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "青岛": "101120200",
    "合肥": "101220100", "厦门": "101230200", "福州": "101230100",
}

# 猎聘检索用 dqs 城市码（已实测：010 北京 / 020 上海 / 050020 广州 / 050090 深圳 / 150020 郑州）
LIE_PIN_CITY_CODES = {
    "北京": "010", "上海": "020", "天津": "030", "重庆": "040",
    "广州": "050020", "深圳": "050090", "苏州": "060080", "南京": "060020",
    "杭州": "070020", "郑州": "150020", "武汉": "170020", "大连": "210040",
    "西安": "270020", "成都": "280020",
}

# 智联招聘检索用 jl 城市码（取自官方筛选接口 hotCity/allCity，已逐城实测）
ZHILIAN_CITY_CODES = {
    "北京": "530", "上海": "538", "广州": "763", "深圳": "765",
    "杭州": "653", "南京": "635", "苏州": "639", "成都": "801",
    "武汉": "736", "西安": "854", "天津": "531", "重庆": "551",
    "长沙": "749", "郑州": "719", "青岛": "703", "合肥": "664",
    "厦门": "682", "福州": "681",
}

# 前程无忧检索用 6 位城市码（取自官方 dd_city.json，已逐城实测）
JOB51_CITY_CODES = {
    "北京": "010000", "上海": "020000", "广州": "030200", "深圳": "040000",
    "杭州": "080200", "南京": "070200", "苏州": "070300", "成都": "090200",
    "武汉": "180200", "西安": "200200", "天津": "050000", "重庆": "060000",
    "长沙": "190200", "郑州": "170200", "青岛": "120300", "合肥": "150200",
    "厦门": "110300", "福州": "110200",
}


def city_code(platform_key, city_name):
    """把意向城市名映射为平台的检索城市码。未配置的城市会显式报错，避免静默搜错城市。"""
    name = str(city_name or "").strip().removesuffix("市")
    if platform_key == "boss":
        if name.isdigit():
            return name
        if not name:
            return "100010000"
        if name not in BOSS_CITY_CODES:
            raise ValueError("暂未配置 Boss 城市编码：%s，请在 platforms.py 补充" % name)
        return BOSS_CITY_CODES[name]
    if platform_key in ("liepin", "job51", "zhilian"):
        table = {"liepin": LIE_PIN_CITY_CODES,
                 "job51": JOB51_CITY_CODES,
                 "zhilian": ZHILIAN_CITY_CODES}[platform_key]
        label = {"liepin": "猎聘", "job51": "前程无忧", "zhilian": "智联"}[platform_key]
        if not name:
            return ""
        if name.isdigit():
            return name
        if name not in table:
            raise ValueError("暂未配置%s城市编码：%s，请在 platforms.py 补充" % (label, name))
        return table[name]
    return name


def cookie_domain(platform_key):
    return COOKIE_DOMAINS.get(platform_key, "")


def search_url(platform_key, keyword, city="", page=1, api=False):
    from urllib.parse import quote
    p = get(platform_key)
    if not p:
        raise ValueError("未知平台：%s" % platform_key)
    return p["api_url" if api else "search_url"].format(
        keyword=quote(str(keyword), safe=""),
        city=quote(str(city_code(platform_key, city)), safe=""), page=int(page))


def job_url(platform_key, value):
    from urllib.parse import urljoin, quote
    link = str(value or "")
    if not link:
        return ""
    if link.startswith(("http://", "https://", "//", "/")):
        return urljoin(get(platform_key)["login_url"], link)
    templates = {"boss": "https://www.zhipin.com/job_detail/%s.html",
                 "lagou": "https://www.lagou.com/jobs/%s.html",
                 "job51": "https://jobs.51job.com/all/%s.html"}
    return templates[platform_key] % quote(link, safe="") if platform_key in templates else link
