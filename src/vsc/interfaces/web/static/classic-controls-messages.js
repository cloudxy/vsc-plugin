// Explicit software labels only; all other locales use the established English fallback.
import {MESSAGES} from './i18n-messages.js';
const labels={
  translate:['翻译','Translate'],optimize:['优化','Improve'],recognize:['智能识别','Describe images'],
  smart_refs:['智能引用','Use reference images'],smart_hint:['助手读取已添加的参考图片；不改变生成引用。','The assistant reads attached images; generation references stay fixed.'],
  language:['翻译目标语言','Translation language'],suggestion:['提示词建议','Prompt suggestion'],
  apply:['应用建议','Apply suggestion'],discard:['收起建议','Dismiss suggestion'],
  changed:['输入已改变，保留原建议供对照。请以当前输入重新发起，旧建议不会覆盖新稿。','Inputs changed. The original suggestion stays available for comparison and cannot overwrite this draft.'],
  unknown:['原请求回执待确认，只恢复该请求，不重复调用助手。','The original request receipt is pending. Recover this request without another assistant call.'],
  recover:['恢复助手请求','Recover assistant request'],working:['正在准备提示词建议…','Preparing a prompt suggestion…'],
  suggestion_only:['建议只在你点击应用后写入当前提示词。','Suggestions change the prompt only when you apply them.'],
  all:['全部','All'],favorites:['收藏','Favorites'],local:['本地','Local'],favorite:['收藏此结果','Favorite result'],unfavorite:['取消收藏','Remove favorite'],
  result_filter:['结果筛选','Result filter'],local_hint:['本地：本镜头中有原上传或导入记录且不是生成任务输出的素材。','Local: media in this shot with original upload or import records, excluding generation outputs.'],
  generate:['生成','Generate'],quote_hint:['先核对当前输入与真实报价，再确认生成。','Review the current inputs and actual quote before confirming generation.'],
  parameters:['生成参数','Generation settings'],ratio:['画幅','Aspect ratio'],width:['图像宽度','Image width'],height:['图像高度','Image height'],duration:['时长（秒）','Duration (seconds)'],count:['候选数量','Result count'],
  config:['连接与配置详情','Connection and configuration details'],model:['生成模型','Generation model'],
  config_choice:['同模型连接 {value}','Connection {value} for this model'],failed:['助手未完成：{value}。原输入已保留。','Assistant did not complete: {value}. Your inputs are preserved.']
};
for(const [key,[zh,en]]of Object.entries(labels))MESSAGES['classic_controls.'+key]={'zh-cn':zh,en};
