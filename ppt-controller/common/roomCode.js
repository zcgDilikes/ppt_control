export const ROOM_RE = /^[A-Z0-9]{6}$/;

/**
 * 解析扫码结果：与 ppt_pc_client 二维码一致；支持去杂后 6 位或由非字母数字分隔的 6 位段。
 * @param {string} raw
 * @returns {string|null}
 */
export function parseRoomFromScan(raw) {
	if (raw == null || typeof raw !== 'string') return null;
	const compact = raw.trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
	if (compact.length === 6 && ROOM_RE.test(compact)) {
		return compact;
	}
	const upper = raw.trim().toUpperCase();
	const tokens = upper.split(/[^A-Z0-9]+/).filter(Boolean);
	for (let i = 0; i < tokens.length; i++) {
		const t = tokens[i];
		if (t.length === 6 && ROOM_RE.test(t)) {
			return t;
		}
	}
	return null;
}
