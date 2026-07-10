<script setup lang="ts">
import { ref } from 'vue';

const categories = [
	{ id: 'all', label: 'All', count: 24 },
	{ id: 'installed', label: 'Installed', count: 6 },
	{ id: 'finance', label: 'Finance' },
	{ id: 'sales', label: 'Sales' },
	{ id: 'support', label: 'Support' },
	{ id: 'research', label: 'Research' },
	{ id: 'documents', label: 'Documents' },
	{ id: 'operations', label: 'Operations' },
	{ id: 'custom', label: 'Custom' },
];

const activeCategory = ref('all');

const featuredAgents = [
	{
		id: 'finance',
		name: 'Finance Agent',
		description: 'Handles invoices, expenses, cash flow, GST, and reconciliation.',
		icon: '💰',
		iconBg: 'bg-green-50 text-green-600',
		tools: ['Tally', 'Google Sheets', 'Gmail'],
	},
	{
		id: 'email',
		name: 'Email Agent',
		description: 'Reads emails, drafts replies, schedules meetings, and more.',
		icon: '📧',
		iconBg: 'bg-purple-50 text-purple-600',
		tools: ['Gmail', 'Outlook', 'Calendar'],
	},
	{
		id: 'browser',
		name: 'Browser Agent',
		description: 'Logs into websites, downloads reports, submits forms.',
		icon: '🌐',
		iconBg: 'bg-blue-50 text-blue-600',
		tools: ['Chrome', 'Safari', 'Firefox'],
	},
	{
		id: 'sql',
		name: 'SQL Agent',
		description: 'Writes and executes SQL queries and analyzes data.',
		icon: '🛢️',
		iconBg: 'bg-yellow-50 text-yellow-600',
		tools: ['PostgreSQL', 'MySQL', 'SQLite'],
	},
	{
		id: 'support',
		name: 'Support Agent',
		description: 'Answers customer queries and manages support tickets.',
		icon: '🎧',
		iconBg: 'bg-red-50 text-red-600',
		tools: ['Slack', 'Zendesk', 'Intercom'],
	},
	{
		id: 'document',
		name: 'Document Agent',
		description: 'Reads documents, extracts data, summarizes, and creates reports.',
		icon: '📄',
		iconBg: 'bg-emerald-50 text-emerald-600',
		tools: ['PDF', 'Google Drive', 'OneDrive'],
	},
];
</script>

<template>
	<div class="mb-10">
		<!-- Filter Bar -->
		<div class="flex items-center gap-2 overflow-x-auto pb-4 mb-6 border-b border-gray-100 no-scrollbar">
			<button
				v-for="cat in categories"
				:key="cat.id"
				class="flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium transition-colors border"
				:class="[
					activeCategory === cat.id
						? 'bg-black text-white border-black'
						: 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
				]"
				@click="activeCategory = cat.id"
			>
				{{ cat.label }}
				<span
					v-if="cat.count !== undefined"
					class="ml-1.5 px-1.5 py-0.5 rounded-full text-xs"
					:class="activeCategory === cat.id ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'"
				>
					{{ cat.count }}
				</span>
			</button>

			<div class="flex-1"></div>

			<!-- Filter Icon -->
			<button class="flex-shrink-0 p-2 text-gray-400 hover:text-gray-600 transition-colors border border-gray-200 rounded-lg ml-2 bg-white">
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
				</svg>
			</button>
		</div>

		<!-- Featured Agents Header -->
		<div class="flex justify-between items-center mb-4">
			<h2 class="text-xl font-bold text-gray-900">Featured Agents</h2>
			<a href="#" class="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors">View all</a>
		</div>

		<!-- Agent Cards Grid -->
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
			<div
				v-for="agent in featuredAgents"
				:key="agent.id"
				class="bg-white border border-gray-200 rounded-2xl p-5 hover:shadow-md transition-shadow flex flex-col h-full"
			>
				<div class="w-12 h-12 rounded-xl flex items-center justify-center mb-4 text-2xl" :class="agent.iconBg">
					{{ agent.icon }}
				</div>
				
				<h3 class="font-bold text-gray-900 mb-2">{{ agent.name }}</h3>
				<p class="text-sm text-gray-500 leading-relaxed mb-6 flex-1">{{ agent.description }}</p>
				
				<div class="flex items-center gap-2 mb-4">
					<!-- Fake tool icons for demo -->
					<div v-for="tool in agent.tools.slice(0,3)" :key="tool" class="w-6 h-6 rounded bg-gray-100 flex items-center justify-center text-xs text-gray-500 font-bold" :title="tool">
						{{ tool.charAt(0) }}
					</div>
					<div v-if="agent.tools.length > 3" class="w-6 h-6 flex items-center justify-center text-xs text-gray-400">
						...
					</div>
				</div>
				
				<button class="w-full py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
					Install
				</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
/* Hide scrollbar for Chrome, Safari and Opera */
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
/* Hide scrollbar for IE, Edge and Firefox */
.no-scrollbar {
  -ms-overflow-style: none;  /* IE and Edge */
  scrollbar-width: none;  /* Firefox */
}
</style>
