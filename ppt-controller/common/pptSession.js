import { ROOM_RE } from './roomCode.js';

/** 与 WebSocket 会话一致：仅「已连接」期间为 true，供发文件等跨 tab 校验 */
export const STORAGE_PPT_WS_CONNECTED = 'ppt_ws_connected';

/** 当前已连接的房间号（6 位），与上传 URL / formData 的 roomId 一致 */
export const STORAGE_PPT_ACTIVE_ROOM = 'ppt_active_room';

export function syncPptSessionOnConnected(roomId) {
	const id = (roomId || '').trim().toUpperCase();
	if (!ROOM_RE.test(id)) return;
	try {
		uni.setStorageSync(STORAGE_PPT_WS_CONNECTED, true);
		uni.setStorageSync(STORAGE_PPT_ACTIVE_ROOM, id);
	} catch (e) {
		// ignore
	}
}

export function clearPptSession() {
	try {
		uni.setStorageSync(STORAGE_PPT_WS_CONNECTED, false);
		uni.removeStorageSync(STORAGE_PPT_ACTIVE_ROOM);
	} catch (e) {
		// ignore
	}
}

/** 首页常用功能排序（与 tabbar-1 按钮一致） */
export const STORAGE_FAVORITE_TOOL_ORDER = 'ppt_favorite_tool_order';

export const DEFAULT_TOOL_ORDER = [
	'PREV_PAGE',
	'NEXT_PAGE',
	'SCREENSHOT',
	'EXIT',
	'FULL_SCREEN',
	'SEND_TEXT',
	'SELECT_ALL',
	'COPY',
	'PASTE',
	'DELETE',
	'FROM_CURRENT',
	'OPEN_PPT',
	'BLACK_SCREEN',
	'WHITE_SCREEN',
	'SPOTLIGHT',
	'TIMER',
	'PC_WINDOW_MINIMIZE',
	'PC_WINDOW_RESTORE'
];

export const TOOL_MAP = {
	PREV_PAGE: { label: '上一页', cmd: 'PREV_PAGE', span: 1, accent: false, icon: 'chevron-left' },
	NEXT_PAGE: { label: '下一页', cmd: 'NEXT_PAGE', span: 1, accent: false, icon: 'chevron-right' },
	SCREENSHOT: { label: '截屏', cmd: 'SCREENSHOT', span: 1, icon: 'camera' },
	FULL_SCREEN: { label: '从头放映 (F5)', cmd: 'FULL_SCREEN', span: 1, icon: 'maximize' },
	EXIT: { label: '退出放映 (Esc)', cmd: 'EXIT', span: 2, icon: 'x-circle' },
	SEND_TEXT: { label: '发文本', cmd: 'SEND_TEXT', span: 1, special: 'sendText', icon: 'send' },
	SELECT_ALL: { label: '全选', cmd: 'SELECT_ALL', span: 1, icon: 'check-square' },
	COPY: { label: '复制', cmd: 'COPY', span: 1, icon: 'copy' },
	PASTE: { label: '粘贴', cmd: 'PASTE', span: 1, icon: 'clipboard' },
	DELETE: { label: '删除', cmd: 'DELETE', span: 1, icon: 'delete' },
	OPEN_PPT: { label: '启动 PPT', cmd: 'OPEN_PPT', span: 1, icon: 'presentation' },
	FROM_CURRENT: { label: '从当前放映', cmd: 'FROM_CURRENT', span: 1, icon: 'play-circle' },
	BLACK_SCREEN: { label: '黑屏', cmd: 'BLACK_SCREEN', span: 1, icon: 'eye-off' },
	WHITE_SCREEN: { label: '白屏', cmd: 'WHITE_SCREEN', span: 1, icon: 'sun' },
	SPOTLIGHT: { label: '聚光灯', cmd: 'SPOTLIGHT_SHOW', span: 1, special: 'spotlight', icon: 'flashlight' },
	TIMER: { label: '计时器', cmd: 'TIMER', span: 1, special: 'timer', icon: 'timer' },
	PC_WINDOW_MINIMIZE: { label: 'PC端最小化', cmd: 'PC_WINDOW_MINIMIZE', span: 1, icon: 'minimize-2' },
	PC_WINDOW_RESTORE: { label: 'PC端恢复', cmd: 'PC_WINDOW_RESTORE', span: 1, icon: 'maximize-2' }
};

export function getToolOrder() {
	try {
		const raw = uni.getStorageSync(STORAGE_FAVORITE_TOOL_ORDER);
		if (raw == null || raw === '') return [...DEFAULT_TOOL_ORDER];
		const arr = typeof raw === 'string' ? JSON.parse(raw) : raw;
		if (!Array.isArray(arr)) return [...DEFAULT_TOOL_ORDER];
		const valid = arr.filter((id) => TOOL_MAP[id]);
		const missing = DEFAULT_TOOL_ORDER.filter((id) => !valid.includes(id));
		return [...valid, ...missing];
	} catch (e) {
		return [...DEFAULT_TOOL_ORDER];
	}
}

export function saveToolOrder(order) {
	const ids = order.filter((id) => TOOL_MAP[id]);
	try {
		uni.setStorageSync(STORAGE_FAVORITE_TOOL_ORDER, JSON.stringify(ids));
	} catch (e) {
		// ignore
	}
}

export function getResolvedToolList() {
	return getToolOrder()
		.map((id) => {
			const m = TOOL_MAP[id];
			if (!m) return null;
			return {
				id,
				label: m.label,
				cmd: m.cmd,
				span: m.span,
				accent: !!m.accent,
				special: m.special || null,
				icon: m.icon || 'settings'
			};
		})
		.filter(Boolean);
}

/** 与 PC 端 ppt_pc_client_settings.json 中布尔开关对应（不含 open_ppt_path） */
const STORAGE_PPT_CLIENT_SETTINGS = 'ppt_client_settings';

const PPT_CLIENT_SETTINGS_DEFAULTS = {
	screenshot_open_folder: true,
	transfer_open_folder: true,
	transfer_open_ppt: true,
	ppt_notes_enabled: false
};

function _parseStoredClientSettings(raw) {
	if (raw == null || raw === '') return null;
	let obj = raw;
	if (typeof raw === 'string') {
		try {
			obj = JSON.parse(raw);
		} catch (e) {
			return null;
		}
	}
	return obj && typeof obj === 'object' ? obj : null;
}

export function loadPptClientSettings() {
	const out = { ...PPT_CLIENT_SETTINGS_DEFAULTS };
	try {
		const raw = uni.getStorageSync(STORAGE_PPT_CLIENT_SETTINGS);
		const o = _parseStoredClientSettings(raw);
		if (!o) return out;
		if (typeof o.screenshot_open_folder === 'boolean') {
			out.screenshot_open_folder = o.screenshot_open_folder;
		}
		if (typeof o.transfer_open_folder === 'boolean') {
			out.transfer_open_folder = o.transfer_open_folder;
		}
		if (typeof o.transfer_open_ppt === 'boolean') {
			out.transfer_open_ppt = o.transfer_open_ppt;
		}
		if (typeof o.ppt_notes_enabled === 'boolean') {
			out.ppt_notes_enabled = o.ppt_notes_enabled;
		}
	} catch (e) {
		// ignore
	}
	return out;
}

export function savePptClientSettings(partial) {
	const merged = { ...loadPptClientSettings(), ...partial };
	try {
		uni.setStorageSync(STORAGE_PPT_CLIENT_SETTINGS, merged);
	} catch (e) {
		// ignore
	}
	return merged;
}
