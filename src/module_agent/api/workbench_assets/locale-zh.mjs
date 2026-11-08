/** Chinese presentation only: never rewrite stored results, code or evidence. */
const messages = new Map(Object.entries({
  "Reproduction plan requires clarification": "复现方案仍需补充信息和确认细节。",
  "Reproduction plan has required sections": "复现方案包含必要章节，但不代表论文已复现。",
  "Reproduction plan is structurally complete": "复现方案的章节结构完整，但不代表实现或实验已经完成。",
  "Reproduction plan is missing required sections": "复现方案缺少必要内容。",
  "Reproduction artifact has no reproduction plan": "当前产物缺少复现方案。",
  "Generated files are an unverified reproduction scaffold, not a completed implementation of the paper": "生成的文件只是未经验证的复现骨架，不是已完成的论文实现。",
  "Repository license could not be identified": "未识别到仓库许可证。",
  "Repository has no recognized dependency manifest": "未找到可识别的依赖清单。",
  "Repository dependency manifest found": "已找到仓库依赖清单。",
  "Repository artifact has no local path": "产物缺少本地工作目录。",
  "Repository workspace does not exist": "仓库工作目录不存在。",
  "Repository workspace exists": "仓库工作目录已找到。",
  "Repository has no README file": "仓库缺少项目说明文件。",
  "Repository README file found": "已找到项目说明文件。",
  "Repository license file found": "已找到仓库许可证文件。",
  "Repository license found in artifact metadata": "已从产物信息中找到许可证。",
  "Repository artifact has no commit SHA": "产物缺少固定的代码版本标识。",
  "Unable to read repository HEAD commit": "无法读取仓库当前代码版本。",
  "Repository head commit does not match artifact commit SHA": "仓库当前代码版本与记录不一致。",
  "Repository head commit matches artifact commit SHA": "仓库代码版本与记录一致。",
  "Python syntax check timed out": "Python 语法检查超时。",
  "Python syntax check failed": "Python 语法检查失败。",
  "Repository has no Python source files": "仓库没有可检查的 Python 源码。",
  "Python source syntax is valid": "Python 源码语法检查通过。",
  "Python import check timed out": "Python 模块导入检查超时。",
  "Python import check failed": "Python 模块导入检查失败。",
  "Requested Python modules imported successfully": "指定的 Python 模块导入成功。",
  "Smoke test timed out": "冒烟测试超时。",
  "Smoke test failed": "冒烟测试失败。",
  "Smoke test passed": "冒烟测试通过。",
  "Repository has no installable Python package": "仓库没有可安装的 Python 包，已跳过。",
  "Project validation timed out": "项目验证超时。",
  "Project tests failed": "项目测试失败。",
  "Project tests passed": "项目测试通过。",
  "Dependency installation failed": "依赖安装失败。",
  "Dependencies installed successfully": "依赖安装成功。",
  "Workflow deadline exceeded": "工作流执行时间超过了允许的上限。",
  "Valid bearer authentication is required": "需要连接认证，请在连接设置填写有效的 API Token。",
  "Repository URL found on a paper or supplementary-material page": "论文页面或补充材料中提供了该仓库链接。",
  "MNIST dataset (28x28 grayscale images of handwritten digits)": "MNIST 数据集：28×28 像素的手写数字灰度图像。",
  "Predicted digit class (0-9) for each input image": "每张输入图像的数字类别预测（0—9）。",
  "Quantized integer weight files": "量化后的整数权重文件。",
  "Pure C inference source code": "C 语言推理源码。",
  "Logic gate hardware design files": "逻辑门硬件设计文件。",
}));
const normalize = (value) => String(value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim();
const catalog = new Map([...messages].map(([key, value]) => [normalize(key).toLowerCase(), value]));
export const hasChinese = (value) => /[\u3400-\u9fff]/u.test(String(value ?? ""));

export function dependencyDisplay(value) {
  return String(value).replace(/\s*\((?:for|used for)\b[^)]*\)/gi, "").replace(/\s+or\s+/g, " 或 ");
}

/** Unknown prose is not a fabricated translation: retain it as an original. */
export function chineseMessage(value, fallback = "这条说明尚无中文译文，可展开查看原文。") {
  const original = String(value ?? "").trim();
  const text = normalize(original);
  let translated = catalog.get(text.toLowerCase());
  if (!translated && hasChinese(original)) return { text: original, original: null };
  if (!translated && /^Paper method extraction failed/i.test(text)) translated = "部分论文的方法信息未能提取，可查看原始原因。";
  if (!translated && /parameter count.*FLOPs.*exceptionally small/i.test(text)) translated = "摘要报告的参数量和计算量很小，但现有资料没有说明如何实现，需要核对完整网络结构。";
  const footprint = text.match(/exactly\s+([\d,]+)\s+parameters and\s+([\d,]+)\s+FLOPs.*results in\s*~?([\d,]+)\s+parameters/i);
  if (!translated && footprint) translated = `候选结构与论文不一致：资料报告 ${footprint[1]} 个参数、${footprint[2]} FLOPs，生成的示例约有 ${footprint[3]} 个参数，尚不能视为原论文实现。`;
  if (!translated && /pure logic gate circuits.*highly complex/i.test(text)) translated = "纯逻辑门电路实现较复杂，可能需要额外的硬件设计；目前资料不足以确定具体方案。";
  if (!translated && /Pure C implementations.*compiler intrinsics.*alignment/i.test(text)) translated = "单片机 C 实现还依赖编译器指令和内存对齐规则，现有资料没有给出这些细节。";
  if (!translated && /bit-width.*not specified.*int8.*int32/i.test(text)) translated = "资料没有明确量化位宽；当前示例自行采用 int8 权重和 int32 激活值／累加器，这不是已经确认的论文配置。";
  if (!translated && /activation function.*not detailed.*ReLU/i.test(text)) translated = "资料没有明确激活函数及硬件近似方式；当前示例自行采用 ReLU，仍需核对论文。";
  if (!translated && /pure C implementation.*logic gate.*out of scope/i.test(text)) translated = "当前只生成 Python 量化推理示例，没有实现单片机 C 代码或逻辑门电路。";
  if (!translated && /No datasets or weights are downloaded/i.test(text)) translated = "没有下载数据或权重。运行示例前，仍需提供预处理图像和量化权重。";
  if (!translated && /^What is the exact layer-by-layer configuration/i.test(text)) translated = "需要明确逐层网络结构，包括卷积核、步长、通道数和池化配置，才能核对参数量与计算量。";
  if (!translated && /^What is the specific bit-width/i.test(text)) translated = "需要确认整数权重量化采用的具体位宽。";
  if (!translated && /^What activation function/i.test(text)) translated = "需要确认激活函数，以及整数运算或硬件中的近似实现。";
  if (!translated && /^What specific.*microcontroller/i.test(text)) translated = "需要确认目标单片机的型号与硬件条件。";
  if (!translated && /^What is the target technology.*logic gate/i.test(text)) translated = "需要确认逻辑门实现面向的硬件平台，例如 FPGA、ASIC 或离散逻辑芯片。";
  if (!translated && /Designing and deploying.*Convolutional Neural Network.*handwritten digit/i.test(text)) translated = "为手写数字识别设计资源开销较小的卷积网络，面向单片机与逻辑门硬件部署。";
  return { text: translated || fallback, original: original && original !== translated ? original : null };
}

/** Merge repeated artifact/report warnings, preserving distinct originals. */
export function chineseWarnings(...groups) {
  const result = new Map();
  const seen = new Set();
  for (const raw of groups.flat().filter(Boolean)) {
    const key = normalize(raw).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const message = chineseMessage(raw, "还有未提供中文译文的技术说明，请展开查看原文。");
    if (!result.has(message.text)) result.set(message.text, { text: message.text, originals: [] });
    if (message.original) result.get(message.text).originals.push(message.original);
  }
  return [...result.values()];
}

/** User-facing outcome, not a mutation of the stored validation status. */
export function artifactOutcome(artifact, report) {
  if (artifact.status === "failed" || report?.status === "failed") return { label: "处理或检查失败", color: "red", next: "查看检查明细和提醒，排除问题后再继续。" };
  if (artifact.status === "reproduction_planned") {
    const plan = artifact.reproduction_plan;
    const clarification = plan?.open_questions?.length || plan?.warnings?.length || report?.checks?.some((check) => check.kind === "reproduction_plan" && check.status === "warning");
    return clarification
      ? { label: "待补充论文信息（未复现）", color: "amber", next: "获取论文全文，核对网络结构、实现假设和待确认问题后，再验证候选代码。" }
      : { label: artifact.implementation_generated ? "候选代码待验证" : "仅生成复现方案", color: "amber", next: "当前尚无论文指标对照，请先确认方案，再按授权范围验证代码。" };
  }
  return { label: report?.status === "partial" ? "检查有提醒" : report?.status === "passed" ? "当前检查通过" : "尚未完成验证", color: report?.status === "passed" ? "green" : "amber", next: "当前检查结果不代表论文实验指标已经复现。" };
}

/** Readable Chinese outline for legacy plans; not a verbatim translation. */
export function legacyPlanOutline(plan) {
  const text = [plan.research_problem, ...(plan.implementation_steps || [])].join(" ");
  const steps = [
    [/\benvironment\b|\bdata preparation\b|\bpreprocess(?:ing)?\b/i, "准备运行环境和数据，核对输入预处理与数据划分。"],
    [/\barchitecture\b|\bforward pass\b|\btrain(?:ing|ed)?\b/i, "核对论文网络结构和训练配置，再建立模型。"],
    [/\bquantization\b|\bquantized\b/i, "确认量化位宽、缩放方式和精度影响。"],
    [/\bpure C\b|\bmicrocontrollers?\b/i, "如需单片机部署，还要确认 C 实现、编译器和硬件约束。"],
    [/\blogic gates?\b|\bVerilog\b|\bVHDL\b/i, "如需逻辑门实现，还要设计并验证相应硬件电路。"],
    [/\bevaluation\b|\bprofil(?:e|ing)\b|\baccuracy\b|\blatency\b/i, "按方案开展准确率、参数量、计算量及资源占用对照；目前不代表已经执行。"],
  ].filter(([pattern]) => pattern.test(text)).map(([, explanation]) => explanation);
  return steps.length ? steps : ["这是历史英文方案，尚无可靠的中文步骤摘要。请查看完整原文，或在后续任务中生成中文方案。"];
}
