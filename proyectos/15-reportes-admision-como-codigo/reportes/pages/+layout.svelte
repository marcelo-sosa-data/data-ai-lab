<script>
	import '@evidence-dev/tailwind/fonts.css';
	import '../app.css';
	import { EvidenceDefaultLayout } from '@evidence-dev/core-components';
	export let data;
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link
		rel="stylesheet"
		href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap"
	/>
</svelte:head>

<EvidenceDefaultLayout
	{data}
	title="Admisión Universidad Mirasol"
	homePageName="Inicio"
	hideBreadcrumbs={true}
	builtWithEvidence={false}
	neverShowQueries={true}
	hideTOC={true}
>
	<slot slot="content" />
</EvidenceDefaultLayout>

<style>
	:global(body) {
		font-family: 'Inter', sans-serif;
	}
	:global(.text-xl.font-medium),
	:global(td),
	:global(code) {
		font-family: 'JetBrains Mono', monospace;
		font-variant-numeric: tabular-nums;
	}
	:global(td) {
		font-size: 0.8rem;
	}
	:global(h1) {
		letter-spacing: -0.01em;
	}
</style>
