<template>
	<view class="ppt-icon" :style="wrapStyle">
		<rich-text :nodes="svgNodes" />
	</view>
</template>

<script>
import { ICON_MAP } from '../../common/iconMap.js';

/**
 * SVG 矢量图标组件（基于 Lucide Icons，MIT License）
 * 用法：<ppt-icon name="chevron-left" :size="24" color="#333" />
 */
export default {
	name: 'PptIcon',
	props: {
		/** ICON_MAP 中的键名，如 "chevron-left" */
		name: { type: String, default: '' },
		/** 图标尺寸（数字=px，字符串原样传入，如 "40rpx"） */
		size: { type: [Number, String], default: 24 },
		/** 描边颜色，默认跟随父元素文字色 */
		color: { type: String, default: 'currentColor' }
	},
	computed: {
		wrapStyle() {
			const s = typeof this.size === 'number' ? this.size + 'px' : this.size;
			return `width:${s};height:${s};line-height:0;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;`;
		},
		svgNodes() {
			const inner = ICON_MAP[this.name] || '';
			const pxSize = typeof this.size === 'number' ? this.size : parseInt(this.size) || 24;
			const strokeColor = this.color === 'currentColor' ? 'inherit' : this.color;

			return [
				{
					name: 'svg',
					attrs: {
						xmlns: 'http://www.w3.org/2000/svg',
						viewBox: '0 0 24 24',
						width: String(pxSize),
						height: String(pxSize),
						fill: 'none',
						stroke: strokeColor,
						'stroke-width': '2',
						'stroke-linecap': 'round',
						'stroke-linejoin': 'round'
					},
					children: this._parseSvgInner(inner, strokeColor)
				}
			];
		}
	},
	methods: {
		/**
		 * 将 SVG 内层 HTML 字符串解析为 rich-text nodes 数组
		 * 支持自闭合标签：<path .../>, <circle .../>, <line .../>,
		 *               <rect .../>, <polyline .../>, <polygon .../>,
		 *               <ellipse .../>, <text .../>
		 */
		_parseSvgInner(html, strokeColor) {
			if (!html) return [];
			const nodes = [];
			// 匹配自闭合 SVG 元素
			const tagRe = /<([a-zA-Z][a-zA-Z0-9]*)([^>]*?)\/>/g;
			let m;
			while ((m = tagRe.exec(html)) !== null) {
				const tag = m[1];
				const attrsStr = m[2] || '';
				const attrs = {};
				// 解析属性
				const attrRe = /([\w-:]+)="([^"]*)"/g;
				let am;
				while ((am = attrRe.exec(attrsStr)) !== null) {
					attrs[am[1]] = am[2];
				}
				// 确保描边色能正确渲染（部分环境不继承）
				if (!attrs.stroke) {
					attrs.stroke = strokeColor;
				}
				if (!attrs.fill) {
					attrs.fill = 'none';
				}
				nodes.push({ name: tag, attrs });
			}
			return nodes;
		}
	}
};
</script>

<style scoped>
.ppt-icon {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	line-height: 0;
	vertical-align: middle;
}
</style>
