/**
 * WebSocket 服务地址：需与运行 ppt_pc_client.py 的中继为同一主机/端口。
 * 正式版微信小程序仅允许 wss，且须在公众平台配置 socket 合法域名；开发阶段可在开发者工具「详情」中关闭域名校验。
 * WS_PATH_TEMPLATE：须与后端一致；最终地址为 wss://ppt.dilikes.com/ws/mini/{roomId}（mini/ 后为 6 位房间号）。
 */
/** 小程序协议版本号，需与 ppt_pc_client.py 中 MINI_PROTOCOL_VERSION 一致 */
export const MINI_PROTOCOL_VERSION = 2;

export const WS_BASE = 'wss://ppt.dilikes.com';

/** 与 WS_BASE 同主机端口，用于 multipart 上传等 HTTP 接口 */
export function getHttpOriginFromWsBase() {
	return WS_BASE.replace(/^wss:/i, 'https:').replace(/\/$/, '');
}

/** POST multipart：字段 file + formData.roomId（roomId 仅走表单，不在 URL 路径中） */
export function buildFileUploadUrl() {
	const origin = getHttpOriginFromWsBase();
	return `${origin}/file/upload`;
}

/**
 * 与服务端 WebSocketServer 一致：小程序 /ws/mini/{roomId}，PC（Python）须连 /ws/python/{roomId}（见 RoomManager）。
 */
export const WS_PATH_TEMPLATE = '/ws/mini/{roomId}';

export function buildWsUrl(roomId) {
	const path = WS_PATH_TEMPLATE.replace(/\{roomId\}/g, encodeURIComponent(roomId));
	const base = WS_BASE.replace(/\/$/, '');
	const p = path.startsWith('/') ? path : `/${path}`;
	return `${base}${p}`;
}
