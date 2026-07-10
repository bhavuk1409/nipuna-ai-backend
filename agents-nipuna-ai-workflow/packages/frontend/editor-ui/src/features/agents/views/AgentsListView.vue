<script setup lang="ts">
import debounce from 'lodash/debounce';
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from '@n8n/i18n';
import { useRootStore } from '@n8n/stores/useRootStore';
import { DEBOUNCE_TIME, DEFAULT_WORKFLOW_PAGE_SIZE, getDebounceTime } from '@/app/constants';
import { useDebounce } from '@/app/composables/useDebounce';
import { useProjectsStore } from '@/features/collaboration/projects/projects.store';
import { useDocumentTitle } from '@/app/composables/useDocumentTitle';
import {
	listAgentsPage,
	listAgentsPageGlobal,
	type ListAgentsSortBy,
} from '../composables/useAgentApi';
import { useAgentPermissions } from '../composables/useAgentPermissions';
import { useAgentTelemetry } from '../composables/useAgentTelemetry';
import type { AgentResource } from '../types';
import { AGENT_BUILDER_VIEW, NEW_AGENT_VIEW } from '../constants';
import type { BaseFilters, SortingAndPaginationUpdates } from '@/Interface';

// Custom Dashboard Components
import AgentsDashboardHero from '../components/dashboard/AgentsDashboardHero.vue';
import FeaturedAgentsList from '../components/dashboard/FeaturedAgentsList.vue';
import AgentsDashboardSidebar from '../components/dashboard/AgentsDashboardSidebar.vue';

function isAgentResource(value: unknown): value is AgentResource {
	return typeof value === 'object' && value !== null && 'id' in value;
}

const locale = useI18n();
const documentTitle = useDocumentTitle();

const route = useRoute();
const router = useRouter();
const rootStore = useRootStore();
const projectsStore = useProjectsStore();
const agentTelemetry = useAgentTelemetry();
const { callDebounced } = useDebounce();

const homeProject = computed(() => projectsStore.currentProject ?? projectsStore.personalProject);

const { canCreate: canCreateAgent } = useAgentPermissions(
	() => projectId.value ?? homeProject.value?.id,
);

const allAgents = ref<AgentResource[]>([]);
const filters = ref<BaseFilters>({ search: '', homeProject: '' });
const currentPage = ref(1);
const pageSize = ref(DEFAULT_WORKFLOW_PAGE_SIZE);
const currentSort = ref<ListAgentsSortBy>('updatedAt:desc');
const totalAgents = ref(0);
const loading = ref(true);

const projectId = computed(() => route.params.projectId as string | undefined);

async function fetchAgents() {
	const shouldDelayLoading = allAgents.value.length > 0;
	const delayedLoading = debounce(() => {
		loading.value = true;
	}, getDebounceTime(DEBOUNCE_TIME.INPUT.SEARCH));

	if (shouldDelayLoading) {
		delayedLoading();
	} else {
		loading.value = true;
	}

	try {
		const fetchOptions = {
			skip: (currentPage.value - 1) * pageSize.value,
			take: pageSize.value,
			sortBy: currentSort.value,
			filter: filters.value.search ? { query: filters.value.search } : undefined,
		};
		const { count, data } = projectId.value
			? await listAgentsPage(rootStore.restApiContext, projectId.value, fetchOptions)
			: await listAgentsPageGlobal(rootStore.restApiContext, fetchOptions);
		allAgents.value = data;
		totalAgents.value = count;
	} finally {
		delayedLoading.cancel();
		loading.value = false;
	}
}

function onCreateAgentClick() {
	agentTelemetry.trackClickedNewAgent('button');
	const targetProjectId = projectId.value ?? projectsStore.personalProject?.id;
	void router.push({ name: NEW_AGENT_VIEW, query: { projectId: targetProjectId } });
}

function onGenerateAgentClick(prompt: string) {
	agentTelemetry.trackClickedNewAgent('button'); // Reuse new agent track for now
	const targetProjectId = projectId.value ?? projectsStore.personalProject?.id;
	void router.push({ name: NEW_AGENT_VIEW, query: { projectId: targetProjectId, prompt } });
}

onMounted(async () => {
	documentTitle.set(locale.baseText('agents.heading'));
	await fetchAgents();
});
</script>

<template>
	<div class="h-full w-full overflow-y-auto bg-white pt-6 pb-12">
		<div class="max-w-[1400px] mx-auto px-6 lg:px-8 flex gap-8">
			<!-- Main Content -->
			<div class="flex-1 min-w-0">
				<AgentsDashboardHero 
					@create-agent="onCreateAgentClick"
					@generate-agent="onGenerateAgentClick"
				/>
				
				<FeaturedAgentsList />

				<!-- My Agents Section -->
				<div class="mt-12 mb-12">
					<h2 class="text-xl font-bold text-gray-900 mb-4">My Agents</h2>
					
					<div v-if="allAgents.length === 0" class="bg-gray-50/50 border border-gray-100 rounded-3xl p-12 flex flex-col items-center justify-center text-center">
						<div class="w-16 h-16 bg-white border border-gray-200 rounded-2xl flex items-center justify-center mb-5 text-3xl shadow-sm">
							🤖
						</div>
						<h3 class="font-bold text-gray-900 mb-2">You haven't created any agents yet</h3>
						<p class="text-sm text-gray-500 mb-6 max-w-sm">
							Create your first agent or use AI to generate one in seconds.
						</p>
						<button
							class="bg-black text-white px-5 py-2.5 rounded-lg font-medium hover:bg-gray-800 transition-colors"
							@click="onCreateAgentClick"
						>
							+ Create Your First Agent
						</button>
					</div>
					<div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
						<div v-for="agent in allAgents" :key="agent.id" class="p-5 border border-gray-200 rounded-2xl hover:shadow-md transition-shadow bg-white">
							<h3 class="font-bold text-gray-900 mb-2">{{ agent.name }}</h3>
							<p class="text-sm text-gray-500 line-clamp-2">Agent ready for automation tasks.</p>
						</div>
					</div>
				</div>
			</div>

			<!-- Right Sidebar -->
			<AgentsDashboardSidebar />
		</div>
	</div>
</template>
