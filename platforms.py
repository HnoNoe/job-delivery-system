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
        "api_url": "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query={keyword}&city=101010100&page={page}&pageSize=30",
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
        "search_url": "https://sou.zhaopin.com/?jl={city}&kw={keyword}&p={page}",
        "item_selector": "div.joblist-box__item",
        "fields": {
            "岗位名称": ".jobinfo__name",
            "单位名称": ".companyinfo__name",
            "岗位链接": "a.joblist-box__iteminfo",
            "城市": ".jobinfo__other-info",
        },
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
        "search_url": "https://www.liepin.com/zhaopin/?key={keyword}&city={city}&page={page}",
        "item_selector": "div.job-list-item",
        "fields": {
            "岗位名称": ".job-title-box .ellipsis-1",
            "单位名称": ".company-name",
            "岗位链接": "a",
            "城市": ".job-dq-box",
        },
        "login_check": {"type": "url_not_contains", "value": "login"},
        "headless_ok": False,
    },
    "job51": {
        "name": "前程无忧",
        "login_url": "https://login.51job.com/",
        "login_qr_selector": "img.qrcode, .login-qrcode img, canvas",
        "search_url": "https://we.51job.com/pc/search?jobArea={city}&keyword={keyword}&pageNum={page}",
        "item_selector": "div.joblist_item",
        "fields": {
            "岗位名称": ".job_name",
            "单位名称": ".cname",
            "岗位链接": "a",
            "城市": ".job_area",
        },
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


def city_code(platform_key, city_name):
    """把意向城市名映射为平台的检索城市码。Boss直聘有专门码表，其它平台暂用城市名。"""
    if platform_key == "boss":
        return BOSS_CITY_CODES.get(city_name, "101010100")  # 默认北京
    return city_name or ""


def cookie_domain(platform_key):
    return COOKIE_DOMAINS.get(platform_key, "")
