// 从自己的运行服务录制真实页面。--live会调用已配置的模型，产生费用和学习记录。
import {chromium, expect} from "@playwright/test";
import {readFile, mkdir, writeFile} from "node:fs/promises";
import {resolve} from "node:path";

const args = process.argv.slice(2);
function option(name, fallback) {const index = args.indexOf(name); return index < 0 ? fallback : args[index + 1];}
const passwordFile = option("--password-file");
if (!passwordFile) throw new Error("需要--password-file；不得把密码写到源码或命令参数中");
const baseURL = option("--url", "http://127.0.0.1:8000");
const live = args.includes("--live");
await mkdir("docs/images", {recursive: true});
await mkdir("artifacts/recordings", {recursive: true});
const browser = await chromium.launch({channel: process.env.STUDY_BROWSER_CHANNEL || "chrome"});
const auth = await browser.newContext({baseURL});
const login = await auth.request.post("/api/login", {headers: {Origin: baseURL}, data: {password: (await readFile(passwordFile, "utf8")).trim()}});
if (!login.ok()) throw new Error("服务登录失败");
const storageState = await auth.storageState(); // 只保留在内存中，不写出会话凭据。
const context = await browser.newContext({baseURL, storageState, viewport: {width: 1280, height: 900}, recordVideo: {dir: "artifacts/recordings", size: {width: 1280, height: 900}}});
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const pauses = ms => new Promise(resolve => setTimeout(resolve, ms));
async function shot(name) {
  if (!await page.getByRole("dialog").isVisible() && await page.locator(".notice").isVisible()) await page.getByLabel("关闭提示").click();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({path: `docs/images/${name}.png`, fullPage: true});
  console.log("已拍摄真实页面：" + name);
  await pauses(1400);
}
const steps = [];
let generated;
try {
  await page.goto("/#settings");
  await expect(page.getByRole("heading", {name: "设置", exact: true})).toBeVisible();
  if (await page.getByLabel("API 密钥", {exact: true}).inputValue()) throw new Error("设置页不应回显密钥");
  if (live) {
    await page.getByRole("button", {name: "保存模型配置", exact: true}).click();
    await page.getByRole("button", {name: "测试已保存的连接", exact: true}).click();
    await expect(page.getByText("连接成功，已收到模型的真实回复", {exact: true})).toBeVisible({timeout: 180000});
    steps.push("浏览器保存自配模型和真实连接测试");
  }
  await shot("settings");
  await page.getByRole("button", {name: "资料库", exact: true}).click();
  await shot("library");
  const state = await (await context.request.get("/api/state")).json();
  const doc = state.documents.find(value => value.format === "json");
  if (!doc) throw new Error("需要先导入原创示例资料");
  await page.getByRole("button", {name: "阅读", exact: true}).first().click();
  await page.getByRole("button", {name: /三种备份方式/}).first().click();
  await expect(page.locator(".content-blocks")).toContainText("增量备份复制");
  if (live && await page.getByRole("button", {name: "标记已读", exact: true}).isVisible()) {
    await page.getByRole("button", {name: "标记已读", exact: true}).click();
    await expect(page.getByRole("button", {name: "已读 · 点击撤销", exact: true})).toBeVisible();
  }
  await shot("reader");
  await page.getByRole("button", {name: "提问这份资料", exact: true}).click();
  if (live) {
    await page.getByLabel("问题内容", {exact: true}).fill("周一完整备份后，周二和周三做增量或差异备份，恢复到周三分别需要什么？");
    await page.getByRole("button", {name: "发送问题", exact: true}).click();
    await expect(page.getByText("出处定位已核对；结论仍需结合原文检查。", {exact: true})).toBeVisible({timeout: 240000});
    steps.push("浏览器真实流式问答、出处展开及原文定位");
  } else {
    await page.getByLabel("问答历史").click();
    await page.locator(".chat-history button").first().click();
  }
  await page.locator(".chat-dialog .source-links summary").first().click();
  await page.locator(".chat-body").evaluate(element => {element.scrollTop = 0;});
  await shot("qa");
  await page.locator(".chat-dialog").getByRole("button", {name: "定位到原文"}).first().click();
  await expect(page.locator(".chat-dialog")).toHaveCount(0);
  await pauses(1300);
  await page.getByRole("button", {name: "练习复习", exact: true}).click();
  if (live) {
    await page.getByRole("button", {name: "生成练习题", exact: true}).click();
    await page.getByLabel("主题（可选）", {exact: true}).fill("恢复演练与备份范围：避免覆盖原文件、识别校验值的限制");
    const result = page.waitForResponse(response => response.url().endsWith("/api/questions/generate") && response.request().method() === "POST", {timeout: 240000});
    await page.getByRole("button", {name: "生成并保存", exact: true}).click();
    const response = await result;
    if (!response.ok()) throw new Error("真实出题失败，请在页面检查错误后重试");
    generated = await response.json();
    if (generated.created + generated.duplicates !== 3) throw new Error("真实生成题数与请求不符");
    await expect(page.getByRole("status")).toContainText("已保存", {timeout: 10000});
    console.log(`已验证真实出题保存：新增${generated.created}题、跳过${generated.duplicates}道重复题`);
    steps.push("浏览器真实生成3题与待核对标识");
  }
  await shot("practice");
  const after = await (await context.request.get("/api/state")).json();
  const q = after.questions.find(value => value.origin === "ai" && !state.questions.some(old => old.id === value.id)) || after.questions.find(value => value.origin === "ai");
  if (!q) throw new Error("没有可展示的真实AI参考题");
  await page.locator(".question-row").filter({hasText: q.stem}).first().click();
  if (live && !q.latest) {
    await page.getByRole("radio").first().check();
    await page.getByRole("button", {name: "提交答案", exact: true}).click();
    await expect(page.locator(".answer-result")).toBeVisible();
    steps.push("浏览器参考题作答、参考答案和原文出处");
  }
  await expect(page.locator(".source-links summary").first()).toBeVisible();
  await page.locator(".source-links summary").first().click();
  await shot("question");
  await page.getByRole("button", {name: "学习计划", exact: true}).click();
  if (live) {
    await page.getByLabel("每天学习项数").fill("3");
    await page.getByRole("button", {name: /^(生成学习计划|重新安排剩余内容)$/}).click();
    await expect(page.getByRole("status")).toContainText("已安排");
    steps.push("浏览器按剩余资料和题目创建计划并查看真实统计");
  }
  await shot("plan");
  await page.getByRole("button", {name: "今日学习", exact: true}).click();
  await shot("today");
  const finalState = await (await context.request.get("/api/state")).json();
  const video = page.video();
  await context.close();
  const videoPath = await video.path();
  const mobile = await browser.newContext({baseURL, storageState, viewport: {width: 390, height: 844}});
  const phone = await mobile.newPage();
  await phone.goto("/#reader/" + state.chunks.find(value => value.document_id === doc.id && value.section === "三种备份方式").id);
  await expect(phone.locator(".content-blocks")).toContainText("增量备份复制");
  if (await phone.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error("窄屏正文存在横向溢出");
  await phone.screenshot({path: "docs/images/mobile.png"});
  await mobile.close();
  if (errors.length) throw new Error("页面出现运行错误");
  await writeFile("artifacts/capture-result.json", JSON.stringify({verified_at: new Date().toISOString(), live, browser: browser.version(), steps, generated, video: resolve(videoPath), stats: finalState.stats}, null, 2));
  console.log("真实页面录制完成，原始录屏保存在忽略目录artifacts/recordings");
} finally {await browser.close();}
