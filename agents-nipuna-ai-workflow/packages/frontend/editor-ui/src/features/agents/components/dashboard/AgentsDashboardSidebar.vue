<script setup lang="ts">
const recentActivity = [
	{
		id: 1,
		agentName: 'Finance Agent',
		status: 'Completed successfully',
		statusColor: 'bg-green-500',
		timeAgo: '3m ago',
		icon: '💰',
		iconBg: 'bg-green-50',
	},
	{
		id: 2,
		agentName: 'Email Agent',
		status: 'Waiting for approval',
		statusColor: 'bg-yellow-500',
		timeAgo: '8m ago',
		icon: '📧',
		iconBg: 'bg-purple-50',
	},
	{
		id: 3,
		agentName: 'Browser Agent',
		status: 'Completed successfully',
		statusColor: 'bg-green-500',
		timeAgo: '15m ago',
		icon: '🌐',
		iconBg: 'bg-blue-50',
	},
	{
		id: 4,
		agentName: 'Support Agent',
		status: 'Execution failed',
		statusColor: 'bg-red-500',
		timeAgo: '25m ago',
		icon: '🎧',
		iconBg: 'bg-red-50',
	},
	{
		id: 5,
		agentName: 'SQL Agent',
		status: 'Completed successfully',
		statusColor: 'bg-green-500',
		timeAgo: '1h ago',
		icon: '🛢️',
		iconBg: 'bg-yellow-50',
	},
];

const quickActions = [
	{
		id: 'browse',
		title: 'Browse Templates',
		description: 'Install pre-built agents',
		icon: 'grid',
	},
	{
		id: 'import',
		title: 'Import Agent',
		description: 'Import from JSON or URL',
		icon: 'download',
	},
	{
		id: 'create',
		title: 'Create from Workflow',
		description: 'Convert workflow to agent',
		icon: 'git-merge',
	},
	{
		id: 'docs',
		title: 'Agent Documentation',
		description: 'Learn how agents work',
		icon: 'book',
	},
];
</script>

<template>
	<div class="w-80 shrink-0 hidden lg:block">
		<!-- Recent Activity -->
		<div class="bg-white border border-gray-200 rounded-2xl p-5 mb-6 shadow-sm">
			<div class="flex justify-between items-center mb-6">
				<h2 class="font-bold text-gray-900">Recent Activity</h2>
				<a href="#" class="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors">View all</a>
			</div>
			
			<div class="space-y-5">
				<div v-for="activity in recentActivity" :key="activity.id" class="flex items-start gap-3">
					<div class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" :class="activity.iconBg">
						{{ activity.icon }}
					</div>
					<div class="flex-1 min-w-0">
						<h4 class="text-sm font-bold text-gray-900 truncate">{{ activity.agentName }}</h4>
						<p class="text-xs text-gray-500 truncate mt-0.5">{{ activity.status }}</p>
					</div>
					<div class="flex items-center gap-2 shrink-0">
						<span class="text-xs text-gray-400">{{ activity.timeAgo }}</span>
						<div class="w-1.5 h-1.5 rounded-full" :class="activity.statusColor"></div>
					</div>
				</div>
			</div>
		</div>

		<!-- Quick Actions -->
		<div class="bg-gray-50 border border-gray-100 rounded-2xl p-5 shadow-sm">
			<h2 class="font-bold text-gray-900 mb-4">Quick Actions</h2>
			
			<div class="space-y-2">
				<button
					v-for="action in quickActions"
					:key="action.id"
					class="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-white hover:shadow-sm transition-all text-left group border border-transparent hover:border-gray-200"
				>
					<div class="w-8 h-8 rounded-lg bg-white border border-gray-200 flex items-center justify-center text-gray-500 shrink-0 group-hover:text-black">
						<!-- Placeholder for N8nIcon or raw SVG. We'll use simple SVGs to ensure it renders fine -->
						<svg v-if="action.icon === 'grid'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
						<svg v-else-if="action.icon === 'download'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
						<svg v-else-if="action.icon === 'git-merge'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"></circle><circle cx="6" cy="6" r="3"></circle><path d="M6 21V9a9 9 0 0 0 9 9"></path></svg>
						<svg v-else-if="action.icon === 'book'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
					</div>
					<div class="flex-1">
						<h4 class="text-sm font-semibold text-gray-900">{{ action.title }}</h4>
						<p class="text-xs text-gray-500 mt-0.5">{{ action.description }}</p>
					</div>
					<svg class="text-gray-300 group-hover:text-gray-500" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
				</button>
			</div>
		</div>
	</div>
</template>
