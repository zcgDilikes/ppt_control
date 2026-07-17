<template>

	<view class="page" @touchmove="onPageTouchMove" @touchend="onPageTouchEnd" @touchcancel="onPageTouchEnd">

		<view class="card">

			<text class="title">关于</text>

			<text class="desc">PPT 遥控小程序 · 在本页拖动可调整首页常用功能顺序（含翻页、发送文本、全选等），返回首页后立即生效。</text>

		</view>



		<view class="card preview-card">
			<text class="section-title">首页快捷区预览</text>
			<text class="hint">排序前 5 项映射到五个位置（左上→左下→右上→右下→中心）</text>
			<view class="preview-grid">
				<view class="preview-slot preview-slot--tl">
					<text class="preview-label">{{ previewLabel(0) }}</text>
					<text class="preview-pos">左上</text>
				</view>
				<view class="preview-slot preview-slot--tr">
					<text class="preview-label">{{ previewLabel(2) }}</text>
					<text class="preview-pos">右上</text>
				</view>
				<view class="preview-slot preview-slot--mid">
					<text class="preview-label preview-label--lg">{{ previewLabel(4) }}</text>
					<text class="preview-pos">中心</text>
				</view>
				<view class="preview-slot preview-slot--bl">
					<text class="preview-label">{{ previewLabel(1) }}</text>
					<text class="preview-pos">左下</text>
				</view>
				<view class="preview-slot preview-slot--br">
					<text class="preview-label">{{ previewLabel(3) }}</text>
					<text class="preview-pos">右下</text>
				</view>
			</view>
		</view>

		<view class="card">

			<text class="section-title">常用工具排序</text>

			<text class="hint">按住左侧 ⋮⋮ 竖条上下拖动调整顺序</text>

			<view class="sort-list" id="sortList">

				<block v-for="(id, index) in sortList" :key="id">

					<view v-if="index === 0" class="group-label">常用功能</view>

					<view v-if="index === favGroupSize && sortList.length > favGroupSize" class="group-label">触控板</view>

					<view

						class="sort-row"

						:class="{

							'is-dragging': dragIndex === index,

							'is-hover': dragIndex !== null && hoverIndex === index && dragIndex !== index,

							'is-last-row': index === sortList.length - 1

						}"

					>

						<view

							class="drag-handle"

							@touchstart.stop.prevent="onHandleStart(index, $event)"

							@touchmove.stop.prevent="onHandleMove($event)"

							@touchend.stop="onDragEnd"

							@touchcancel.stop="onDragEnd"

						>

							⋮⋮

						</view>

						<text class="row-label">{{ toolLabel(id) }}</text>

					</view>

				</block>

			</view>

		</view>

	</view>

</template>



<script>

import { getToolOrder, saveToolOrder, TOOL_MAP } from '../../../common/pptSession.js';



export default {

	data() {

		return {

			sortList: [],

			/** 与首页快捷区一致：排序前若干项为「常用功能」，其余为「触控板」 */

			favGroupSize: 5,

			dragIndex: null,

			hoverIndex: null,

			_listTop: 0,

			_rowH: 48,

			_rowRects: []

		};

	},

	onLoad() {

		this.sortList = getToolOrder();

	},

	onShow() {

		this.sortList = getToolOrder();

		this.$nextTick(() => {

			this.measureSortList();

		});

	},

	onReady() {

		this.$nextTick(() => {

			this.measureSortList();

		});

	},

	methods: {

		toolLabel(id) {

			return (TOOL_MAP[id] && TOOL_MAP[id].label) || id;

		},

		previewLabel(index) {

			const id = this.sortList[index];

			if (!id) return '—';

			const t = TOOL_MAP[id];

			return t ? t.label : id;

		},

		measureSortList(done) {

			const q = uni.createSelectorQuery().in(this);

			q.select('.sort-list').boundingClientRect();

			q.selectAll('.sort-row').boundingClientRect();

			q.exec((res) => {

				if (res && res[0]) this._listTop = res[0].top;

				const rows = res && res[1];

				if (Array.isArray(rows) && rows.length) {

					this._rowRects = rows.map((r) => ({

						top: r.top,

						bottom: r.bottom,

						height: r.height

					}));

					const h0 = rows[0].height;

					if (h0) this._rowH = h0;

				} else {

					this._rowRects = [];

				}

				if (typeof done === 'function') done();

			});

		},

		onHandleStart(index, e) {

			const t = e.touches && e.touches[0];

			const y = t ? t.clientY : 0;

			this.dragIndex = index;

			this.hoverIndex = index;

			this.measureSortList(() => {

				this.updateHoverFromY(y);

			});

		},

		onHandleMove(e) {

			if (this.dragIndex === null) return;

			const t = e.touches && e.touches[0];

			if (t) this.updateHoverFromY(t.clientY);

		},

		onPageTouchMove(e) {

			if (this.dragIndex === null) return;

			const t = e.touches && e.touches[0];

			if (t) this.updateHoverFromY(t.clientY);

		},

		onDragEnd() {

			this.commitDragOrder();

		},

		onPageTouchEnd() {

			this.commitDragOrder();

		},

		commitDragOrder() {

			if (this.dragIndex === null) return;

			const from = this.dragIndex;

			const to = this.hoverIndex;

			if (to !== null && to !== undefined && from !== to) {

				const item = this.sortList[from];

				const next = [...this.sortList];

				next.splice(from, 1);

				next.splice(to, 0, item);

				this.sortList = next;

				saveToolOrder(next);

				this.$nextTick(() => {

					this.measureSortList();

				});

			}

			this.dragIndex = null;

			this.hoverIndex = null;

		},

		updateHoverFromY(clientY) {

			const n = this.sortList.length;

			if (n <= 0) return;

			const rects = this._rowRects;

			if (rects && rects.length === n) {

				let hi = 0;

				let found = false;

				for (let i = 0; i < n; i++) {

					const r = rects[i];

					if (clientY >= r.top && clientY < r.bottom) {

						hi = i;

						found = true;

						break;

					}

				}

				if (!found) {

					let best = 0;

					let bestD = Infinity;

					for (let i = 0; i < n; i++) {

						const r = rects[i];

						const mid = (r.top + r.bottom) / 2;

						const d = Math.abs(clientY - mid);

						if (d < bestD) {

							bestD = d;

							best = i;

						}

					}

					hi = best;

				}

				this.hoverIndex = Math.max(0, Math.min(n - 1, hi));

				return;

			}

			const h = this._rowH || 48;

			const top = this._listTop;

			let hi = Math.floor((clientY - top + h / 2) / h);

			hi = Math.max(0, Math.min(n - 1, hi));

			this.hoverIndex = hi;

		}

	}

};

</script>



<style scoped>

.page {

	min-height: 100vh;

	padding: 24rpx;

	padding-bottom: 48rpx;

	background: #f0f0f0;

	box-sizing: border-box;

}



.card {

	background: #fff;

	border-radius: 16rpx;

	padding: 28rpx;

	margin-bottom: 24rpx;

	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);

}



.title {

	display: block;

	font-size: 34rpx;

	font-weight: 600;

	color: #333;

	margin-bottom: 16rpx;

}



.desc {

	display: block;

	font-size: 26rpx;

	color: #666;

	line-height: 1.55;

}



.section-title {

	display: block;

	font-size: 28rpx;

	font-weight: 600;

	color: #333;

	margin-bottom: 12rpx;

}



.hint {

	display: block;

	font-size: 24rpx;

	color: #999;

	margin-bottom: 24rpx;

	line-height: 1.45;

}



.sort-list {

	border-radius: 12rpx;

	overflow: hidden;

	background: #f8f8f8;

}

.group-label {

	display: block;

	padding: 16rpx 20rpx 10rpx;

	font-size: 24rpx;

	font-weight: 600;

	color: #888;

	background: #f0f0f0;

	border-bottom: 1rpx solid #e5e5e5;

}

.sort-row {

	display: flex;

	align-items: center;

	min-height: 96rpx;

	padding: 0 20rpx;

	border-bottom: 1rpx solid #eee;

	background: #fff;

}

.sort-row.is-last-row {

	border-bottom: none;

}



.sort-row.is-dragging {

	opacity: 0.85;

	background: #fff5f5;

}



.sort-row.is-hover {

	background: #e8f4ff;

}



.drag-handle {

	width: 72rpx;

	min-height: 96rpx;

	display: flex;

	align-items: center;

	justify-content: center;

	font-size: 28rpx;

	color: #bbb;

	letter-spacing: -4rpx;

	margin-right: 16rpx;

	flex-shrink: 0;

}



.row-label {

	flex: 1;

	font-size: 28rpx;

	color: #333;

}

.preview-card {
	padding-bottom: 32rpx;
}

.preview-grid {
	position: relative;
	width: 100%;
	height: 280rpx;
	margin-top: 16rpx;
	background: #f8f8f8;
	border-radius: 16rpx;
	overflow: hidden;
}

.preview-slot {
	position: absolute;
	width: 140rpx;
	height: 110rpx;
	background: #fff;
	border-radius: 12rpx;
	box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.08);
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 6rpx;
}

.preview-slot--tl { top: 16rpx; left: 16rpx; }
.preview-slot--tr { top: 16rpx; right: 16rpx; }
.preview-slot--bl { bottom: 16rpx; left: 16rpx; }
.preview-slot--br { bottom: 16rpx; right: 16rpx; }
.preview-slot--mid {
	top: 50%;
	left: 50%;
	transform: translate(-50%, -50%);
	width: 160rpx;
	height: 120rpx;
	background: linear-gradient(145deg, #fff0f2, #ffe4e8);
	border: 2rpx solid #f33e54;
}

.preview-label {
	font-size: 22rpx;
	color: #333;
	font-weight: 500;
	text-align: center;
	line-height: 1.3;
}

.preview-label--lg {
	font-size: 24rpx;
	font-weight: 600;
	color: #f33e54;
}

.preview-pos {
	font-size: 20rpx;
	color: #aaa;
}

</style>

