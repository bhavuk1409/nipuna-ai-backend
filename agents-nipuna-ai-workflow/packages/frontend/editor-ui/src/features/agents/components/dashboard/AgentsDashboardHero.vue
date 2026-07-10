<script setup lang="ts">
import { ref } from 'vue';

const prompt = ref('');

const emit = defineEmits<{
	'create-agent': [];
	'generate-agent': [prompt: string];
}>();
</script>

<template>
	<div class="mb-10">
		<div class="flex flex-col lg:flex-row justify-between items-start mb-8 gap-8">
			<div class="flex-1">
				<h1 class="text-4xl font-bold mb-3 text-gray-900">Agents</h1>
				<p class="text-gray-500 max-w-md text-lg">
					Create intelligent workers that can reason, use tools, and automate business operations.
				</p>
				<div class="flex gap-4 mt-6">
					<button
						class="bg-black text-white px-5 py-2.5 rounded-lg font-medium flex items-center gap-2 hover:bg-gray-800 transition-colors"
						@click="emit('create-agent')"
					>
						<span class="text-xl leading-none">+</span> Create Agent
					</button>
					<button
						class="bg-white border border-gray-200 text-gray-700 px-5 py-2.5 rounded-lg font-medium flex items-center gap-2 hover:bg-gray-50 transition-colors"
						@click="emit('generate-agent', '')"
					>
						<span class="text-xl leading-none">✨</span> Generate with AI
					</button>
				</div>
			</div>

			<!-- Graphic Visualization placeholder (simplified for now) -->
			<div class="relative w-full lg:w-[500px] h-64 shrink-0 hidden md:block">
				<!-- Mocked connections using SVG -->
				<svg class="absolute inset-0 w-full h-full text-gray-200" style="z-index: 0">
					<!-- Top left to center -->
					<path
						d="M 150 50 Q 250 50 250 128"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-dasharray="4 4"
					/>
					<!-- Top right to center -->
					<path
						d="M 350 50 Q 250 50 250 128"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-dasharray="4 4"
					/>
					<!-- Center left to center -->
					<path
						d="M 50 128 L 200 128"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-dasharray="4 4"
					/>
					<!-- Center right to center -->
					<path
						d="M 450 128 L 300 128"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-dasharray="4 4"
					/>
					<!-- Bottom to center -->
					<path
						d="M 250 200 L 250 160"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-dasharray="4 4"
					/>
				</svg>

				<!-- Node Badges -->
				<!-- Finance Agent -->
				<div
					class="absolute top-4 left-24 bg-white border border-green-100 rounded-full px-3 py-1.5 shadow-sm flex items-center gap-2 z-10"
				>
					<span class="text-green-500">💰</span>
					<span class="text-sm font-semibold text-gray-700">Finance Agent</span>
				</div>

				<!-- Gmail Icon -->
				<div
					class="absolute top-2 left-1/2 -translate-x-1/2 bg-white border border-gray-100 rounded-xl p-2 shadow-sm z-10"
				>
					<span class="text-red-500">📧</span>
				</div>

				<!-- Tally Icon -->
				<div
					class="absolute top-4 right-24 bg-white border border-gray-100 rounded-xl p-2 shadow-sm z-10"
				>
					<span class="text-green-700 font-bold px-1">Tally</span>
				</div>

				<!-- Slack Icon -->
				<div
					class="absolute top-1/2 -translate-y-1/2 left-8 bg-white border border-gray-100 rounded-xl p-2 shadow-sm z-10"
				>
					<span class="text-blue-500">💬</span>
				</div>

				<!-- Browser Agent -->
				<div
					class="absolute top-1/2 -translate-y-1/2 right-4 bg-white border border-purple-100 rounded-full px-3 py-1.5 shadow-sm flex items-center gap-2 z-10"
				>
					<span class="text-purple-500">🌐</span>
					<span class="text-sm font-semibold text-gray-700">Browser Agent</span>
				</div>

				<!-- Research Agent -->
				<div
					class="absolute bottom-8 left-1/2 -translate-x-1/2 bg-white border border-blue-100 rounded-full px-3 py-1.5 shadow-sm flex items-center gap-2 z-10"
				>
					<span class="text-blue-500">🔍</span>
					<span class="text-sm font-semibold text-gray-700">Research Agent</span>
				</div>

				<!-- Center Logo -->
				<div class="absolute inset-0 flex items-center justify-center z-20">
					<div
						class="w-20 h-20 bg-white border border-gray-200 rounded-2xl shadow-sm flex items-center justify-center"
					>
						<div class="w-10 h-10 border-2 border-blue-500 rounded-md rotate-45 flex items-center justify-center relative">
							<div class="w-1.5 h-1.5 bg-blue-500 rounded-full absolute -top-1 -left-1"></div>
							<div class="w-1.5 h-1.5 bg-blue-500 rounded-full absolute -bottom-1 -right-1"></div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Create an agent with AI section -->
		<div class="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm relative">
			<div class="flex items-center gap-2 mb-2">
				<span class="text-xl">✨</span>
				<h3 class="font-semibold text-gray-900 text-lg">Create an agent with AI</h3>
			</div>
			<p class="text-sm text-gray-500 mb-6">
				Describe what you want your agent to do in natural language.
			</p>

			<div
				class="bg-gray-50/50 rounded-xl border border-gray-200 focus-within:border-black focus-within:ring-1 focus-within:ring-black transition-all"
			>
				<textarea
					v-model="prompt"
					class="w-full bg-transparent border-none p-4 text-base resize-none outline-none text-gray-800 placeholder:text-gray-400"
					rows="3"
					placeholder="Example: Create an AI accountant that checks invoices, updates Tally, and emails my accountant."
				></textarea>
				<div class="flex justify-between items-center px-4 pb-4">
					<button class="text-gray-400 hover:text-gray-600 transition-colors">
						<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
						</svg>
					</button>
					<button
						class="bg-black text-white px-5 py-2 rounded-lg font-medium hover:bg-gray-800 transition-colors flex items-center gap-2"
						@click="emit('generate-agent', prompt)"
					>
						Generate Agent
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M5 12h14M12 5l7 7-7 7"/>
						</svg>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
